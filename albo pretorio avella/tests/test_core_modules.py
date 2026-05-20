# -*- coding: utf-8 -*-
"""
Comprehensive test suite for the Albo Pretorio application.
Tests configuration, logging, exceptions, caching, and metrics modules.
"""

import pytest
import time
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil


class TestConfig:
    """Tests for configuration module."""
    
    def test_config_loads_default_values(self):
        """Test that configuration loads with default values."""
        from config import AppConfig
        
        config = AppConfig()
        
        assert config.scraper.delay == 1.0
        assert config.scraper.timeout == 20
        assert config.scraper.max_retries == 3
        assert config.logging.level == "INFO"
        assert config.performance.cache_enabled is True
    
    def test_config_creates_directories(self):
        """Test that configuration creates required directories."""
        from config import AppConfig
        
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            config = AppConfig(data_dir=data_dir)
            
            assert data_dir.exists()
            assert config.data_dir == data_dir
    
    def test_scraper_config_validation(self):
        """Test scraper configuration validation."""
        from config import ScraperConfig
        
        # Valid values
        config = ScraperConfig(delay=2.0, timeout=30)
        assert config.delay == 2.0
        assert config.timeout == 30
        
        # Invalid delay (too low)
        with pytest.raises(Exception):
            ScraperConfig(delay=0.01)
        
        # Invalid delay (too high)
        with pytest.raises(Exception):
            ScraperConfig(delay=15.0)
    
    def test_llm_config_from_env(self):
        """Test LLM configuration loading from environment."""
        from config import LLMConfig
        import os
        
        # Save original value
        original = os.environ.get('GOOGLE_API_KEY')
        
        try:
            os.environ['GOOGLE_API_KEY'] = 'test_key_123'
            config = LLMConfig()
            assert config.api_key == 'test_key_123'
        finally:
            # Restore original value
            if original:
                os.environ['GOOGLE_API_KEY'] = original
            else:
                del os.environ['GOOGLE_API_KEY']
    
    def test_rag_config_validation(self):
        """Test RAG configuration validation."""
        from config import RAGConfig
        
        config = RAGConfig(chunk_size=512, top_k=5)
        assert config.chunk_size == 512
        assert config.top_k == 5
        
        # Invalid chunk_size
        with pytest.raises(Exception):
            RAGConfig(chunk_size=50)
        
        # Invalid top_k
        with pytest.raises(Exception):
            RAGConfig(top_k=25)


class TestLogger:
    """Tests for logging module."""
    
    def test_logger_setup(self):
        """Test logger setup and basic functionality."""
        from logger import setup_logging, get_logger
        import logging
        
        logger = setup_logging(level="DEBUG")
        assert logger is not None
        assert logger.level == logging.DEBUG
    
    def test_get_logger_returns_instance(self):
        """Test that get_logger returns a logger instance."""
        from logger import get_logger
        import logging
        
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "albo_pretorio.test_module"
    
    def test_log_context_manager(self):
        """Test LogContext context manager."""
        from logger import setup_logging, LogContext
        
        logger = setup_logging(level="DEBUG")
        
        with LogContext(logger, user="test", action="scrape") as adapted_logger:
            adapted_logger.info("Test message")
            # Should have context info
            assert adapted_logger.extra is not None
    
    def test_performance_logger(self):
        """Test PerformanceLogger context manager."""
        from logger import setup_logging, PerformanceLogger
        
        logger = setup_logging(level="DEBUG")
        
        with PerformanceLogger(logger, "test_operation"):
            time.sleep(0.1)
        
        # Should log completion time
    
    @patch('logger.RotatingFileHandler')
    def test_file_handler_creation(self, mock_handler):
        """Test that file handler is created when log file is specified."""
        from logger import setup_logging
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            setup_logging(log_file=log_file)
            
            # Verify RotatingFileHandler was called
            mock_handler.assert_called_once()


class TestExceptions:
    """Tests for custom exceptions."""
    
    def test_albo_pretorio_error_basic(self):
        """Test basic AlboPretorioError functionality."""
        from exceptions import AlboPretorioError
        
        error = AlboPretorioError("Test error")
        assert error.message == "Test error"
        assert error.details == {}
        assert error.original_exception is None
    
    def test_albo_pretorio_error_with_details(self):
        """Test AlboPretorioError with details."""
        from exceptions import AlboPretorioError
        
        error = AlboPretorioError(
            "Test error",
            details={"key": "value", "count": 42}
        )
        assert error.details["key"] == "value"
        assert error.details["count"] == 42
    
    def test_albo_pretorio_error_to_dict(self):
        """Test converting exception to dictionary."""
        from exceptions import AlboPretorioError
        
        error = AlboPretorioError("Test error", details={"field": "value"})
        error_dict = error.to_dict()
        
        assert error_dict["error_type"] == "AlboPretorioError"
        assert error_dict["message"] == "Test error"
        assert error_dict["details"]["field"] == "value"
    
    def test_network_error(self):
        """Test NetworkError exception."""
        from exceptions import NetworkError
        
        error = NetworkError(
            url="https://example.com",
            status_code=404,
            message="Not found"
        )
        assert error.details["url"] == "https://example.com"
        assert error.details["status_code"] == 404
    
    def test_parse_error(self):
        """Test ParseError exception."""
        from exceptions import ParseError
        
        error = ParseError(
            url="https://example.com",
            element_type="table"
        )
        assert error.details["url"] == "https://example.com"
        assert error.details["element_type"] == "table"
    
    def test_exception_hierarchy(self):
        """Test exception class hierarchy."""
        from exceptions import (
            AlboPretorioError, ScraperError, NetworkError,
            OCRError, RAGError, ConfigurationError
        )
        
        # All should be subclasses of AlboPretorioError
        assert issubclass(ScraperError, AlboPretorioError)
        assert issubclass(NetworkError, ScraperError)
        assert issubclass(OCRError, AlboPretorioError)
        assert issubclass(RAGError, AlboPretorioError)
        assert issubclass(ConfigurationError, AlboPretorioError)
    
    def test_handle_exception_function(self):
        """Test handle_exception utility function."""
        from exceptions import handle_exception, AlboPretorioError
        
        logger = Mock()
        
        # Test with regular exception
        error = Exception("Test")
        result = handle_exception(error, logger=logger, reraise=False)
        
        assert isinstance(result, AlboPretorioError)
        logger.error.assert_called_once()


class TestCache:
    """Tests for caching module."""
    
    def test_lru_cache_basic_operations(self):
        """Test basic LRU cache operations."""
        from cache import LRUCache
        
        cache = LRUCache(max_size=3)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") is None
    
    def test_lru_cache_eviction(self):
        """Test LRU cache eviction policy."""
        from cache import LRUCache
        
        cache = LRUCache(max_size=3)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # Access key1 to make it recently used
        cache.get("key1")
        
        # Add new key, should evict key2 (least recently used)
        cache.set("key4", "value4")
        
        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
    
    def test_lru_cache_ttl(self):
        """Test LRU cache TTL expiration."""
        from cache import LRUCache
        
        cache = LRUCache(max_size=3, default_ttl=1)
        
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        
        # Wait for expiration
        time.sleep(1.1)
        
        assert cache.get("key1") is None
    
    def test_lru_cache_stats(self):
        """Test LRU cache statistics."""
        from cache import LRUCache
        
        cache = LRUCache(max_size=3)
        
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("key1")
        cache.get("key2")  # Miss
        
        stats = cache.stats()
        
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 2/3
        assert stats["size"] == 1
    
    def test_lru_cache_cleanup_expired(self):
        """Test cleaning up expired entries."""
        from cache import LRUCache
        
        cache = LRUCache(max_size=3, default_ttl=1)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        time.sleep(1.1)
        
        removed = cache.cleanup_expired()
        assert removed == 2
        assert len(cache) == 0
    
    def test_file_cache_basic(self):
        """Test basic file cache operations."""
        from cache import FileCache
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=Path(tmpdir))
            
            cache.set("key1", {"data": [1, 2, 3]})
            result = cache.get("key1")
            
            assert result == {"data": [1, 2, 3]}
    
    def test_file_cache_persistence(self):
        """Test that file cache persists across instances."""
        from cache import FileCache
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            
            # Write to cache
            cache1 = FileCache(cache_dir=cache_dir)
            cache1.set("key1", {"persistent": True})
            
            # Read from new instance
            cache2 = FileCache(cache_dir=cache_dir)
            result = cache2.get("key1")
            
            assert result == {"persistent": True}
    
    def test_cached_decorator(self):
        """Test cached function decorator."""
        from cache import cached
        
        call_count = 0
        
        @cached(ttl=60)
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        # First call
        result1 = expensive_function(5, 3)
        assert result1 == 8
        assert call_count == 1
        
        # Second call (should be cached)
        result2 = expensive_function(5, 3)
        assert result2 == 8
        assert call_count == 1  # Not incremented


class TestMetrics:
    """Tests for metrics collection module."""
    
    def test_metrics_collector_initialization(self):
        """Test metrics collector initialization."""
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        
        assert collector.session_start > 0
        assert len(collector._operations) == 0
        assert len(collector._metric_points) == 0
    
    def test_record_point(self):
        """Test recording metric points."""
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        
        collector.record_point("test.metric", 42.0, tags={"env": "test"})
        
        assert len(collector._metric_points) == 1
        point = collector._metric_points[0]
        assert point.name == "test.metric"
        assert point.value == 42.0
        assert point.tags["env"] == "test"
    
    def test_increment_counter(self):
        """Test counter increment."""
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        
        collector.increment_counter("requests", 5)
        collector.increment_counter("requests", 3)
        
        assert collector._counters["requests"] == 8
    
    def test_set_gauge(self):
        """Test gauge setting."""
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        
        collector.set_gauge("memory.usage", 256.5)
        collector.set_gauge("memory.usage", 512.0)
        
        assert collector._gauges["memory.usage"] == 512.0
    
    def test_operation_tracker(self):
        """Test operation tracking context manager."""
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        
        with collector.start_operation("test_op") as tracker:
            time.sleep(0.1)
            tracker.set_items_processed(10)
        
        assert len(collector._operations) == 1
        op = collector._operations[0]
        assert op.operation_name == "test_op"
        assert op.success is True
        assert op.items_processed == 10
        assert op.duration is not None
        assert op.duration >= 0.1
    
    def test_operation_tracker_failure(self):
        """Test operation tracking with failure."""
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        
        try:
            with collector.start_operation("failing_op"):
                raise ValueError("Test error")
        except ValueError:
            pass
        
        assert len(collector._operations) == 1
        op = collector._operations[0]
        assert op.success is False
        assert op.error_type == "ValueError"
    
    def test_get_summary(self):
        """Test getting metrics summary."""
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        
        with collector.start_operation("op1"):
            time.sleep(0.05)
        
        with collector.start_operation("op1"):
            time.sleep(0.05)
        
        summary = collector.get_summary()
        
        assert summary["total_operations"] == 2
        assert "op1" in summary["operation_statistics"]
        assert summary["operation_statistics"]["op1"]["count"] == 2
    
    def test_export_to_file(self):
        """Test exporting metrics to file."""
        from metrics import MetricsCollector
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir)
            collector = MetricsCollector(output_path=output_path)
            
            collector.increment_counter("test.counter", 5)
            
            output_file = collector.export_to_file("test_metrics.json")
            
            assert output_file.exists()
            
            with open(output_file, 'r') as f:
                data = json.load(f)
            
            assert "summary" in data
            assert "counters" in data["summary"]
    
    def test_track_operation_decorator(self):
        """Test operation tracking decorator."""
        from metrics import track_operation, get_metrics_collector
        
        @track_operation("decorated_function")
        def my_function():
            return 42
        
        result = my_function()
        assert result == 42
        
        collector = get_metrics_collector()
        assert any(op.operation_name == "decorated_function" 
                  for op in collector._operations)


class TestIntegration:
    """Integration tests for multiple modules working together."""
    
    def test_config_and_logging_integration(self):
        """Test configuration and logging work together."""
        from config import AppConfig
        from logger import setup_logging
        
        config = AppConfig()
        logger = setup_logging(config.logging)
        
        logger.info("Integration test")
        assert logger is not None
    
    def test_cache_and_metrics_integration(self):
        """Test caching and metrics work together."""
        from cache import LRUCache, cached
        from metrics import MetricsCollector
        
        collector = MetricsCollector()
        cache = LRUCache(max_size=10)
        
        with collector.start_operation("cached_operation") as tracker:
            # Simulate cached operation
            cache.set("key", "value")
            result = cache.get("key")
            
            tracker.set_items_processed(1)
        
        assert result == "value"
        assert collector._counters["operations.success"] == 1
    
    def test_exception_handling_with_logging(self):
        """Test exception handling integrates with logging."""
        from exceptions import handle_exception, NetworkError
        from logger import setup_logging
        
        logger = setup_logging(level="ERROR")
        
        error = NetworkError(
            url="https://example.com",
            message="Connection failed"
        )
        
        result = handle_exception(error, logger=logger, reraise=False)
        
        assert result is error
        # Logger should have been called
    
    def test_full_workflow_simulation(self):
        """Simulate a complete workflow with all modules."""
        from config import AppConfig
        from logger import setup_logging, PerformanceLogger
        from metrics import MetricsCollector
        from cache import LRUCache
        from exceptions import NetworkError, handle_exception
        
        # Initialize
        config = AppConfig()
        logger = setup_logging(config.logging)
        collector = MetricsCollector()
        cache = LRUCache(max_size=100)
        
        # Simulate scraping workflow
        with collector.start_operation("scraping_session") as session_tracker:
            pages_scraped = 0
            
            for page in range(5):
                with PerformanceLogger(logger, f"scrape_page_{page}"):
                    try:
                        # Check cache
                        cached_result = cache.get(f"page_{page}")
                        
                        if cached_result is None:
                            # Simulate network request
                            time.sleep(0.05)
                            result = f"data_for_page_{page}"
                            cache.set(f"page_{page}", result)
                        else:
                            result = cached_result
                        
                        pages_scraped += 1
                        collector.increment_counter("pages.scraped")
                        
                    except Exception as e:
                        handle_exception(e, logger)
                        collector.increment_counter("errors.page_scrape")
            
            session_tracker.set_items_processed(pages_scraped)
        
        # Verify metrics
        summary = collector.get_summary()
        assert summary["total_operations"] > 0
        assert collector._counters.get("pages.scraped", 0) > 0
        
        # Verify cache
        cache_stats = cache.stats()
        assert cache_stats["size"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
