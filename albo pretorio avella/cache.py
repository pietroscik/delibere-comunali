# -*- coding: utf-8 -*-
"""
Caching module for expensive operations.
Provides LRU caching with TTL support for PDF extraction, OCR, and API calls.
"""

import time
import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Dict, Callable, TypeVar, Generic
from functools import wraps
from dataclasses import dataclass, field
import threading

from logger import get_logger
from config import get_config
from exceptions import CacheError


T = TypeVar('T')


@dataclass
class CacheEntry(Generic[T]):
    """A cached entry with value and metadata."""
    value: T
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def touch(self):
        """Update last accessed time and increment access count."""
        self.last_accessed = time.time()
        self.access_count += 1


class LRUCache(Generic[T]):
    """Thread-safe LRU cache with TTL support."""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[int] = None):
        self.logger = get_logger(__name__)
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry[T]] = {}
        self._lock = threading.Lock()
        
        # Stats
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def _generate_key(self, key: Any) -> str:
        """Generate a string key from any hashable object."""
        if isinstance(key, str):
            return key
        try:
            return hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()
        except (TypeError, ValueError):
            return str(hash(key))
    
    def get(self, key: Any, default: Optional[T] = None) -> Optional[T]:
        """Get a value from the cache."""
        cache_key = self._generate_key(key)
        
        with self._lock:
            if cache_key not in self._cache:
                self.misses += 1
                return default
            
            entry = self._cache[cache_key]
            
            # Check expiration
            if entry.is_expired():
                del self._cache[cache_key]
                self.misses += 1
                return default
            
            # Update access stats
            entry.touch()
            self.hits += 1
            
            return entry.value
    
    def set(self, key: Any, value: T, ttl: Optional[int] = None) -> None:
        """Set a value in the cache."""
        cache_key = self._generate_key(key)
        
        with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.max_size and cache_key not in self._cache:
                self._evict_lru()
            
            # Calculate expiration
            expires_at = None
            if ttl is not None or self.default_ttl is not None:
                expires_at = time.time() + (ttl if ttl is not None else self.default_ttl)
            
            entry = CacheEntry(
                value=value,
                expires_at=expires_at
            )
            
            self._cache[cache_key] = entry
            self.logger.debug(f"Cached key: {cache_key[:16]}...")
    
    def delete(self, key: Any) -> bool:
        """Delete a key from the cache."""
        cache_key = self._generate_key(key)
        
        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()
            self.logger.info("Cache cleared")
    
    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if not self._cache:
            return
        
        # Find LRU entry
        lru_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].last_accessed
        )
        
        del self._cache[lru_key]
        self.evictions += 1
        self.logger.debug(f"Evicted LRU entry: {lru_key[:16]}...")
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, v in self._cache.items()
                if v.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
                removed += 1
        
        if removed > 0:
            self.logger.debug(f"Cleaned up {removed} expired entries")
        
        return removed
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self.hits + self.misses
            hit_rate = self.hits / total if total > 0 else 0
            
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": hit_rate,
                "evictions": self.evictions
            }
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __contains__(self, key: Any) -> bool:
        cache_key = self._generate_key(key)
        with self._lock:
            if cache_key not in self._cache:
                return False
            entry = self._cache[cache_key]
            return not entry.is_expired()


class FileCache(Generic[T]):
    """File-based cache for large objects."""
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        default_ttl: Optional[int] = None
    ):
        self.logger = get_logger(__name__)
        self.cache_dir = cache_dir or get_config().cache_dir / "file_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl or 3600  # 1 hour default
        
        self._metadata_file = self.cache_dir / "metadata.json"
        self._metadata: Dict[str, Dict[str, Any]] = self._load_metadata()
        self._lock = threading.Lock()
    
    def _load_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Load metadata from disk."""
        if self._metadata_file.exists():
            try:
                with open(self._metadata_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def _save_metadata(self) -> None:
        """Save metadata to disk."""
        with open(self._metadata_file, 'w') as f:
            json.dump(self._metadata, f, indent=2)
    
    def _generate_key(self, key: Any) -> str:
        """Generate a safe filename from key."""
        if isinstance(key, str):
            safe_key = "".join(c if c.isalnum() or c in '-_' else '_' for c in key)
            return safe_key[:64]
        return hashlib.md5(str(key).encode()).hexdigest()
    
    def get(self, key: Any, default: Optional[T] = None) -> Optional[T]:
        """Get a value from the file cache."""
        cache_key = self._generate_key(key)
        file_path = self.cache_dir / f"{cache_key}.cache"
        
        with self._lock:
            # Check metadata
            if cache_key not in self._metadata:
                return default
            
            meta = self._metadata[cache_key]
            
            # Check expiration
            if meta.get('expires_at', float('inf')) < time.time():
                self.delete(key)
                return default
            
            # Read file
            if not file_path.exists():
                del self._metadata[cache_key]
                self._save_metadata()
                return default
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Update access time
                meta['last_accessed'] = time.time()
                meta['access_count'] = meta.get('access_count', 0) + 1
                self._save_metadata()
                
                return data
            except Exception as e:
                self.logger.warning(f"Failed to read cache file: {e}")
                return default
    
    def set(self, key: Any, value: T, ttl: Optional[int] = None) -> None:
        """Set a value in the file cache."""
        cache_key = self._generate_key(key)
        file_path = self.cache_dir / f"{cache_key}.cache"
        
        with self._lock:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(value, f, ensure_ascii=False, indent=2)
                
                # Update metadata
                self._metadata[cache_key] = {
                    'created_at': time.time(),
                    'expires_at': time.time() + (ttl if ttl is not None else self.default_ttl),
                    'last_accessed': time.time(),
                    'access_count': 0,
                    'size_bytes': file_path.stat().st_size
                }
                self._save_metadata()
                
                self.logger.debug(f"Cached to file: {cache_key}")
            except Exception as e:
                raise CacheError(
                    key=str(key),
                    message=f"Failed to cache to file: {e}",
                    operation="set"
                )
    
    def delete(self, key: Any) -> bool:
        """Delete a key from the file cache."""
        cache_key = self._generate_key(key)
        file_path = self.cache_dir / f"{cache_key}.cache"
        
        with self._lock:
            deleted = False
            
            if file_path.exists():
                file_path.unlink()
                deleted = True
            
            if cache_key in self._metadata:
                del self._metadata[cache_key]
                self._save_metadata()
                deleted = True
            
            return deleted
    
    def clear(self) -> None:
        """Clear all entries from the file cache."""
        with self._lock:
            for cache_file in self.cache_dir.glob("*.cache"):
                cache_file.unlink()
            self._metadata.clear()
            self._save_metadata()
            self.logger.info("File cache cleared")
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        removed = 0
        current_time = time.time()
        
        with self._lock:
            expired_keys = [
                k for k, v in self._metadata.items()
                if v.get('expires_at', float('inf')) < current_time
            ]
            
            for key in expired_keys:
                file_path = self.cache_dir / f"{key}.cache"
                if file_path.exists():
                    file_path.unlink()
                del self._metadata[key]
                removed += 1
            
            if expired_keys:
                self._save_metadata()
        
        return removed
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_size = sum(
                m.get('size_bytes', 0) for m in self._metadata.values()
            )
            
            return {
                "size": len(self._metadata),
                "total_size_bytes": total_size,
                "cache_dir": str(self.cache_dir)
            }


# Global cache instances
_text_cache: Optional[LRUCache[str]] = None
_pdf_cache: Optional[LRUCache[str]] = None
_file_cache: Optional[FileCache] = None


def get_text_cache() -> LRUCache[str]:
    """Get the global text cache."""
    global _text_cache
    if _text_cache is None:
        config = get_config()
        _text_cache = LRUCache(
            max_size=500,
            default_ttl=config.performance.cache_ttl
        )
    return _text_cache


def get_pdf_cache() -> LRUCache[str]:
    """Get the global PDF extraction cache."""
    global _pdf_cache
    if _pdf_cache is None:
        config = get_config()
        _pdf_cache = LRUCache(
            max_size=100,
            default_ttl=config.performance.cache_ttl * 2  # Longer TTL for PDFs
        )
    return _pdf_cache


def get_file_cache() -> FileCache:
    """Get the global file cache."""
    global _file_cache
    if _file_cache is None:
        config = get_config()
        _file_cache = FileCache(
            default_ttl=config.performance.cache_ttl
        )
    return _file_cache


def cached(ttl: Optional[int] = None, cache_type: str = 'memory'):
    """Decorator for caching function results."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not get_config().performance.cache_enabled:
                return func(*args, **kwargs)
            
            # Generate cache key
            key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
            
            # Get appropriate cache
            if cache_type == 'file':
                cache = get_file_cache()
            elif cache_type == 'pdf':
                cache = get_pdf_cache()
            else:
                cache = get_text_cache()
            
            # Try to get from cache
            result = cache.get(key)
            if result is not None:
                return result
            
            # Compute and cache
            result = func(*args, **kwargs)
            cache.set(key, result, ttl=ttl)
            return result
        
        return wrapper
    return decorator


# Example usage
if __name__ == "__main__":
    # Test LRU cache
    cache = LRUCache(max_size=5, default_ttl=60)
    
    cache.set("key1", "value1")
    print(f"Get key1: {cache.get('key1')}")
    print(f"Cache stats: {cache.stats()}")
    
    # Test file cache
    file_cache = FileCache(default_ttl=60)
    file_cache.set("large_data", {"data": list(range(100))})
    print(f"File cache get: {file_cache.get('large_data')}")
    print(f"File cache stats: {file_cache.stats()}")
    
    # Test decorator
    @cached(ttl=60)
    def expensive_function(x, y):
        time.sleep(0.1)
        return x + y
    
    print(f"First call: {expensive_function(5, 3)}")
    print(f"Second call (cached): {expensive_function(5, 3)}")
