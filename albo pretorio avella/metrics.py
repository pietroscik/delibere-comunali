# -*- coding: utf-8 -*-
"""
Metrics collection and monitoring module.
Tracks performance, errors, and operational metrics for the Albo Pretorio system.
"""

import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
import threading

from logger import get_logger
from config import get_config


@dataclass
class MetricPoint:
    """A single metric data point."""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp,
            "tags": self.tags
        }


@dataclass
class OperationMetrics:
    """Metrics for a single operation."""
    operation_name: str
    start_time: float
    end_time: Optional[float] = None
    success: bool = True
    error_type: Optional[str] = None
    items_processed: int = 0
    bytes_processed: int = 0
    custom_metrics: Dict[str, float] = field(default_factory=dict)
    
    @property
    def duration(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return self.end_time - self.start_time
    
    @property
    def throughput(self) -> Optional[float]:
        if self.duration is None or self.duration == 0:
            return None
        return self.items_processed / self.duration if self.items_processed > 0 else None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_name": self.operation_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "success": self.success,
            "error_type": self.error_type,
            "items_processed": self.items_processed,
            "bytes_processed": self.bytes_processed,
            "throughput": self.throughput,
            "custom_metrics": self.custom_metrics
        }


class MetricsCollector:
    """Thread-safe metrics collector with aggregation capabilities."""
    
    def __init__(self, output_path: Optional[Path] = None):
        self.logger = get_logger(__name__)
        self.output_path = output_path or get_config().output_dir / "metrics"
        self.output_path.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.Lock()
        self._metric_points: List[MetricPoint] = []
        self._operations: List[OperationMetrics] = []
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        
        # Start time for session metrics
        self.session_start = time.time()
    
    def _record_point_internal(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Internal method to record a metric point (assumes lock is already held)."""
        point = MetricPoint(name=name, value=value, tags=tags or {})
        self._metric_points.append(point)
        self.logger.debug(f"Recorded metric: {name}={value}")
    
    def record_point(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Record a single metric data point."""
        with self._lock:
            self._record_point_internal(name, value, tags)
    
    def increment_counter(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
        """Increment a counter metric."""
        key = f"{name}:{json.dumps(tags, sort_keys=True)}" if tags else name
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value
            self._record_point_internal(f"counter.{name}", self._counters[key], tags)
    
    def set_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Set a gauge metric."""
        key = f"{name}:{json.dumps(tags, sort_keys=True)}" if tags else name
        with self._lock:
            self._gauges[key] = value
            self._record_point_internal(f"gauge.{name}", value, tags)
    
    def start_operation(self, operation_name: str) -> 'OperationTracker':
        """Start tracking an operation and return a tracker context."""
        return OperationTracker(self, operation_name)
    
    def record_operation(self, metrics: OperationMetrics):
        """Record completed operation metrics."""
        with self._lock:
            self._operations.append(metrics)
            
            # Update counters
            if metrics.success:
                self.increment_counter("operations.success")
            else:
                self.increment_counter("operations.failure")
            
            self.increment_counter("operations.total")
            
            # Record timing metrics
            if metrics.duration is not None:
                self.record_point(
                    f"operation.duration.{metrics.operation_name}",
                    metrics.duration
                )
            
            if metrics.throughput is not None:
                self.record_point(
                    f"operation.throughput.{metrics.operation_name}",
                    metrics.throughput
                )
            
            self.logger.info(
                f"Operation '{metrics.operation_name}' completed",
                extra=metrics.to_dict()
            )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all collected metrics."""
        with self._lock:
            session_duration = time.time() - self.session_start
            
            # Calculate operation statistics
            op_stats = {}
            for op in self._operations:
                name = op.operation_name
                if name not in op_stats:
                    op_stats[name] = {
                        "count": 0,
                        "total_duration": 0,
                        "successes": 0,
                        "failures": 0
                    }
                
                op_stats[name]["count"] += 1
                if op.duration is not None:
                    op_stats[name]["total_duration"] += op.duration
                if op.success:
                    op_stats[name]["successes"] += 1
                else:
                    op_stats[name]["failures"] += 1
            
            # Calculate averages
            for name, stats in op_stats.items():
                if stats["count"] > 0:
                    stats["avg_duration"] = stats["total_duration"] / stats["count"]
                    stats["success_rate"] = stats["successes"] / stats["count"]
            
            return {
                "session_duration": session_duration,
                "total_operations": len(self._operations),
                "total_metric_points": len(self._metric_points),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "operation_statistics": op_stats
            }
    
    def export_to_file(self, filename: Optional[str] = None) -> Path:
        """Export metrics to a JSON file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"metrics_{timestamp}.json"
        
        output_file = self.output_path / filename
        
        with self._lock:
            data = {
                "exported_at": datetime.now().isoformat(),
                "session_start": self.session_start,
                "summary": self.get_summary(),
                "recent_operations": [op.to_dict() for op in self._operations[-100:]],
                "recent_points": [pt.to_dict() for pt in self._metric_points[-1000:]]
            }
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        self.logger.info(f"Metrics exported to {output_file}")
        return output_file
    
    def clear(self):
        """Clear all collected metrics."""
        with self._lock:
            self._metric_points.clear()
            self._operations.clear()
            self._counters.clear()
            self._gauges.clear()
            self.session_start = time.time()


class OperationTracker:
    """Context manager for tracking operation metrics."""
    
    def __init__(self, collector: MetricsCollector, operation_name: str):
        self.collector = collector
        self.operation_name = operation_name
        self.metrics = OperationMetrics(
            operation_name=operation_name,
            start_time=time.time()
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.metrics.end_time = time.time()
        
        if exc_type is not None:
            self.metrics.success = False
            self.metrics.error_type = exc_type.__name__
        
        self.collector.record_operation(self.metrics)
        return False
    
    def set_items_processed(self, count: int):
        """Set the number of items processed in this operation."""
        self.metrics.items_processed = count
        return self
    
    def set_bytes_processed(self, count: int):
        """Set the number of bytes processed in this operation."""
        self.metrics.bytes_processed = count
        return self
    
    def add_custom_metric(self, name: str, value: float):
        """Add a custom metric to this operation."""
        self.metrics.custom_metrics[name] = value
        return self


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def track_operation(operation_name: str):
    """Decorator for tracking function operations."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            with collector.start_operation(operation_name) as tracker:
                try:
                    result = func(*args, **kwargs)
                    tracker.set_items_processed(1)
                    return result
                except Exception as e:
                    tracker.set_items_processed(0)
                    raise
        return wrapper
    return decorator


# Example usage
if __name__ == "__main__":
    collector = get_metrics_collector()
    
    # Track an operation
    with collector.start_operation("test_scraping") as tracker:
        time.sleep(0.5)
        tracker.set_items_processed(10).set_bytes_processed(1024)
        tracker.add_custom_metric("pages_scraped", 5)
    
    # Record some counters
    collector.increment_counter("documents.downloaded", 5)
    collector.increment_counter("documents.processed", 3)
    
    # Set some gauges
    collector.set_gauge("queue.size", 10)
    collector.set_gauge("memory.usage_mb", 256.5)
    
    # Get summary
    summary = collector.get_summary()
    print(json.dumps(summary, indent=2))
    
    # Export to file
    output_file = collector.export_to_file()
    print(f"Metrics exported to: {output_file}")
