# -*- coding: utf-8 -*-
"""
Configuration management module using Pydantic.
Centralized configuration for the Albo Pretorio scraper and RAG system.
"""

import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv


class ScraperConfig(BaseModel):
    """Configuration for web scraping operations."""
    
    base_url: str = Field(
        default="https://servizi.comune.avella.av.it/openweb/albo/",
        description="Base URL for Albo Pretorio"
    )
    user_agent: str = Field(
        default="CivicResearchBot/1.1 (+contatto: tua-pec-o-email)",
        description="User agent string for HTTP requests"
    )
    delay: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Delay between requests in seconds"
    )
    timeout: int = Field(
        default=20,
        ge=5,
        le=120,
        description="HTTP request timeout in seconds"
    )
    max_pages: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="Maximum number of pages to scrape"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of retry attempts"
    )
    retry_backoff: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Backoff multiplier for retries"
    )
    
    class Config:
        env_prefix = "SCRAPER_"


class OCRConfig(BaseModel):
    """Configuration for OCR operations."""
    
    tesseract_cmd: Optional[str] = Field(
        default=None,
        description="Path to Tesseract executable (optional, auto-detected if not set)"
    )
    lang: str = Field(
        default="ita",
        description="OCR language code"
    )
    psm: int = Field(
        default=3,
        ge=0,
        le=14,
        description="Page segmentation mode for Tesseract"
    )
    oem: int = Field(
        default=1,
        ge=0,
        le=3,
        description="OCR Engine Mode for Tesseract"
    )
    dpi: int = Field(
        default=300,
        ge=150,
        le=600,
        description="DPI for image preprocessing"
    )
    enable_preprocessing: bool = Field(
        default=True,
        description="Enable image preprocessing for better OCR accuracy"
    )
    
    class Config:
        env_prefix = "OCR_"


class LLMConfig(BaseModel):
    """Configuration for LLM operations."""
    
    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv('GOOGLE_API_KEY'),
        description="Google API key for Gemini"
    )
    model_priority: List[str] = Field(
        default=["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"],
        description="Priority order for LLM models (failover)"
    )
    embedding_model_priority: List[str] = Field(
        default=["models/gemini-embedding-001", "models/text-embedding-004"],
        description="Priority order for embedding models"
    )
    use_gemini_by_default: bool = Field(
        default=False,
        description="Start RAG with Gemini active by default"
    )
    use_local_retriever_with_gemini: bool = Field(
        default=True,
        description="Use local retriever when FAISS index is missing"
    )
    max_tokens: int = Field(
        default=4096,
        ge=512,
        le=32768,
        description="Maximum tokens for LLM responses"
    )
    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM generation"
    )
    
    model_config = {
        "env_prefix": "GOOGLE_"
    }


class RAGConfig(BaseModel):
    """Configuration for RAG (Retrieval-Augmented Generation) operations."""
    
    chunk_size: int = Field(
        default=512,
        ge=128,
        le=2048,
        description="Size of text chunks for embedding"
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
        le=512,
        description="Overlap between chunks"
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of top results to retrieve"
    )
    similarity_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold for retrieval"
    )
    enable_hybrid_search: bool = Field(
        default=True,
        description="Enable hybrid search (semantic + keyword)"
    )
    faiss_index_path: Optional[Path] = Field(
        default=None,
        description="Path to FAISS index file"
    )
    
    class Config:
        env_prefix = "RAG_"


class LoggingConfig(BaseModel):
    """Configuration for logging."""
    
    level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format"
    )
    file_path: Optional[Path] = Field(
        default=None,
        description="Path to log file (optional, console only if not set)"
    )
    max_file_size: int = Field(
        default=10485760,  # 10MB
        ge=1048576,
        le=104857600,
        description="Maximum log file size in bytes before rotation"
    )
    backup_count: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of backup log files to keep"
    )
    
    class Config:
        env_prefix = "LOG_"


class PerformanceConfig(BaseModel):
    """Configuration for performance optimizations."""
    
    enable_parallel_pdf: bool = Field(
        default=True,
        description="Enable parallel PDF extraction"
    )
    max_workers: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Maximum number of worker threads/processes"
    )
    batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Batch size for processing"
    )
    cache_enabled: bool = Field(
        default=True,
        description="Enable caching for expensive operations"
    )
    cache_ttl: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Cache time-to-live in seconds"
    )
    
    class Config:
        env_prefix = "PERF_"


class AppConfig(BaseModel):
    """Main application configuration combining all sub-configs."""
    
    scraper: ScraperConfig = Field(default_factory=ScraperConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    
    # Application paths
    data_dir: Path = Field(
        default=Path("./data"),
        description="Directory for storing downloaded data"
    )
    output_dir: Path = Field(
        default=Path("./output"),
        description="Directory for output files"
    )
    cache_dir: Path = Field(
        default=Path("./cache"),
        description="Directory for cache files"
    )
    
    @field_validator('data_dir', 'output_dir', 'cache_dir')
    @classmethod
    def ensure_directories(cls, v):
        if not v.exists():
            v.mkdir(parents=True, exist_ok=True)
        return v
    
    @classmethod
    def load_from_env(cls, env_file: Optional[Path] = None) -> 'AppConfig':
        """Load configuration from environment variables and .env file."""
        if env_file:
            load_dotenv(env_file)
        else:
            # Try to load from default locations
            for path in [Path(".env"), Path("../.env")]:
                if path.exists():
                    load_dotenv(path)
                    break
        
        return cls()


def get_config() -> AppConfig:
    """Get application configuration singleton."""
    if not hasattr(get_config, '_config'):
        get_config._config = AppConfig.load_from_env()
    return get_config._config


if __name__ == "__main__":
    # Example usage and validation
    config = get_config()
    print("Configuration loaded successfully!")
    print(f"Data directory: {config.data_dir}")
    print(f"Logging level: {config.logging.level}")
    print(f"LLM models: {config.llm.model_priority}")
