# -*- coding: utf-8 -*-
"""
Logging module with structured logging support.
Provides centralized logging configuration for the entire application.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

from config import LoggingConfig, get_config


class CustomFormatter(logging.Formatter):
    """Custom formatter with color support for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # Avoid mutating levelname for downstream handlers (e.g. file logging).
        original_level = record.levelname
        log_color = self.COLORS.get(original_level, self.RESET)
        record.levelname = f"{log_color}{original_level}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_level


def setup_logging(
    config: Optional[LoggingConfig] = None,
    log_file: Optional[Path] = None,
    level: Optional[str] = None,
) -> logging.Logger:
    """
    Set up logging with both console and file handlers.
    
    Args:
        config: Logging configuration (uses app config if not provided)
        log_file: Optional path to log file (overrides config)
        level: Optional logging level (overrides config)
    
    Returns:
        Configured logger instance
    """
    if config is None:
        config = get_config().logging
    
    if level is None:
        level = config.level
    
    # Create root logger
    logger = logging.getLogger('albo_pretorio')
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler with colored output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = CustomFormatter(config.format)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler with rotation (if configured)
    file_path = log_file or config.file_path
    if file_path:
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=config.max_file_size,
            backupCount=config.backup_count
        )
        # In tests this class can be patched/mocked; add only valid handlers.
        if isinstance(file_handler, logging.Handler):
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(config.format)
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = __name__) -> logging.Logger:
    """
    Get a logger instance with the specified name.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Logger instance
    """
    logger = logging.getLogger(f'albo_pretorio.{name}')

    # Configure base logger once; child loggers normally do not own handlers.
    base_logger = logging.getLogger("albo_pretorio")
    if not base_logger.handlers:
        setup_logging()

    return logger


class LogContext:
    """Context manager for adding contextual information to logs."""
    
    def __init__(self, logger: logging.Logger, **context):
        self.logger = logger
        self.context = context
        self.adapter = None
    
    def __enter__(self):
        self.adapter = logging.LoggerAdapter(self.logger, self.context)
        return self.adapter
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.adapter.error(
                f"Exception occurred: {exc_val}",
                exc_info=True
            )
        return False


def log_operation(logger: logging.Logger, operation: str, **kwargs):
    """
    Log an operation with structured data.
    
    Args:
        logger: Logger instance
        operation: Operation name
        **kwargs: Additional context data
    """
    logger.info(f"Operation: {operation}", extra=kwargs)


class PerformanceLogger:
    """Context manager for logging performance metrics."""
    
    def __init__(self, logger: logging.Logger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        import time
        self.start_time = time.time()
        self.logger.debug(f"Starting operation: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        elapsed = time.time() - self.start_time
        if exc_type is not None:
            self.logger.error(
                f"Operation {self.operation} failed after {elapsed:.2f}s: {exc_val}"
            )
        else:
            self.logger.debug(
                f"Operation {self.operation} completed in {elapsed:.2f}s"
            )
        return False


# Example usage
if __name__ == "__main__":
    # Setup logging
    logger = setup_logging(log_file=Path("./logs/app.log"))
    
    # Basic logging
    logger.info("Application started")
    logger.debug("Debug message")
    logger.warning("Warning message")
    logger.error("Error message")
    
    # Context logging
    with LogContext(logger, user="test", action="scrape") as adapted_logger:
        adapted_logger.info("Scraping started")
    
    # Performance logging
    with PerformanceLogger(logger, "data_extraction"):
        import time
        time.sleep(0.1)  # Simulate work
    
    logger.info("Application finished")
