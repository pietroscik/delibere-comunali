# -*- coding: utf-8 -*-
"""
Custom exceptions for the Albo Pretorio application.
Provides consistent error handling across the entire codebase.
"""

from typing import Optional, Dict, Any


class AlboPretorioError(Exception):
    """Base exception for all Albo Pretorio errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.original_exception = original_exception
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
            "has_original_exception": self.original_exception is not None
        }


class ScraperError(AlboPretorioError):
    """Base exception for scraper-related errors."""
    pass


class NetworkError(ScraperError):
    """Network-related errors (connection failures, timeouts, etc.)."""
    
    def __init__(
        self,
        url: str,
        message: str = "Network request failed",
        status_code: Optional[int] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"url": url, "status_code": status_code, **kwargs}
        )


class ParseError(ScraperError):
    """HTML/content parsing errors."""
    
    def __init__(
        self,
        url: str,
        message: str = "Failed to parse content",
        element_type: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"url": url, "element_type": element_type, **kwargs}
        )


class RateLimitError(ScraperError):
    """Rate limiting errors."""
    
    def __init__(
        self,
        url: str,
        retry_after: Optional[float] = None,
        message: str = "Rate limit exceeded"
    ):
        super().__init__(
            message=message,
            details={"url": url, "retry_after": retry_after}
        )


class RobotsTxtError(ScraperError):
    """Robots.txt compliance errors."""
    
    def __init__(
        self,
        url: str,
        message: str = "URL disallowed by robots.txt"
    ):
        super().__init__(
            message=message,
            details={"url": url}
        )


class DownloadError(ScraperError):
    """File download errors."""
    
    def __init__(
        self,
        url: str,
        filename: Optional[str] = None,
        message: str = "Failed to download file",
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"url": url, "filename": filename, **kwargs}
        )


class OCRError(AlboPretorioError):
    """OCR processing errors."""
    
    def __init__(
        self,
        filename: str,
        message: str = "OCR processing failed",
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"filename": filename, **kwargs}
        )


class PDFExtractionError(AlboPretorioError):
    """PDF text extraction errors."""
    
    def __init__(
        self,
        filename: str,
        message: str = "Failed to extract text from PDF",
        page_number: Optional[int] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"filename": filename, "page_number": page_number, **kwargs}
        )


class LLMError(AlboPretorioError):
    """LLM/Gemini API errors."""
    
    def __init__(
        self,
        message: str = "LLM operation failed",
        model: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"model": model, **kwargs}
        )


class EmbeddingError(LLMError):
    """Text embedding errors."""
    
    def __init__(
        self,
        message: str = "Failed to generate embeddings",
        model: Optional[str] = None,
        text_length: Optional[int] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            model=model,
            details={"text_length": text_length, **(kwargs if kwargs else {})}
        )


class RAGError(AlboPretorioError):
    """RAG system errors."""
    
    def __init__(
        self,
        message: str = "RAG operation failed",
        operation: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"operation": operation, **kwargs}
        )


class IndexNotFoundError(RAGError):
    """FAISS index not found error."""
    
    def __init__(
        self,
        index_path: str,
        message: str = "FAISS index not found"
    ):
        super().__init__(
            message=message,
            details={"index_path": index_path}
        )


class ConfigurationError(AlboPretorioError):
    """Configuration/validation errors."""
    
    def __init__(
        self,
        key: str,
        message: str = "Invalid configuration",
        value: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"key": key, "value": value, **kwargs}
        )


class ValidationError(AlboPretorioError):
    """Data validation errors."""
    
    def __init__(
        self,
        field: str,
        message: str = "Validation failed",
        value: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"field": field, "value": value, **kwargs}
        )


class CacheError(AlboPretorioError):
    """Caching system errors."""
    
    def __init__(
        self,
        key: str,
        message: str = "Cache operation failed",
        operation: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"key": key, "operation": operation, **kwargs}
        )


class MetricsError(AlboPretorioError):
    """Metrics collection errors."""
    
    def __init__(
        self,
        metric_name: str,
        message: str = "Failed to collect metrics",
        **kwargs
    ):
        super().__init__(
            message=message,
            details={"metric_name": metric_name, **kwargs}
        )


def handle_exception(
    exception: Exception,
    logger=None,
    reraise: bool = False,
    default_exception: Optional[type] = None
):
    """
    Handle an exception with logging and optional re-raising.
    
    Args:
        exception: The exception to handle
        logger: Logger instance for logging the error
        reraise: Whether to re-raise the exception
        default_exception: Default exception type to wrap with
    
    Returns:
        AlboPretorioError instance (if not re-raising)
    """
    from logger import get_logger
    
    if logger is None:
        logger = get_logger()
    
    # If already an AlboPretorioError, log and optionally re-raise
    if isinstance(exception, AlboPretorioError):
        logger.error(
            f"{exception.__class__.__name__}: {exception.message}",
            extra=exception.to_dict(),
            exc_info=True
        )
        if reraise:
            raise
        return exception
    
    # Wrap other exceptions
    wrapped_exception = default_exception(
        message=str(exception),
        original_exception=exception
    ) if default_exception else AlboPretorioError(
        message=str(exception),
        original_exception=exception
    )
    
    logger.error(
        f"{wrapped_exception.__class__.__name__}: {wrapped_exception.message}",
        extra=wrapped_exception.to_dict(),
        exc_info=True
    )
    
    if reraise:
        raise wrapped_exception
    
    return wrapped_exception
