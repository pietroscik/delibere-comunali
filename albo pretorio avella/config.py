# -*- coding: utf-8 -*-
"""
Configuration management module using Pydantic.
Centralized configuration for the Albo Pretorio scraper and RAG system.
"""

import json
import os
from pathlib import Path
from typing import List, Optional, get_origin

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _parse_list_env(value):
    """Accept JSON list or comma-separated values."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return []
        if txt.startswith("["):
            try:
                parsed = json.loads(txt)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
        return [item.strip() for item in txt.split(",") if item.strip()]
    return value


def _load_model_from_env(model_cls, *, env_prefix: str = "", aliases=None):
    """Create a model instance using matching environment variables."""
    payload = {}
    aliases = aliases or {}

    for field_name, field_info in model_cls.model_fields.items():
        candidates = []

        if field_name in aliases:
            candidates.extend(aliases[field_name])

        if env_prefix:
            candidates.append(f"{env_prefix}{field_name}".upper())

        raw_value = None
        for env_name in candidates:
            if env_name in os.environ:
                raw_value = os.environ.get(env_name)
                break

        if raw_value is None:
            continue

        if get_origin(field_info.annotation) in (list, List):
            payload[field_name] = _parse_list_env(raw_value)
        else:
            payload[field_name] = raw_value

    return model_cls(**payload)


class ScraperConfig(BaseModel):
    """Configuration for web scraping operations."""

    base_url: str = Field(
        default="https://servizi.comune.avella.av.it/openweb/albo/",
        description="Base URL for Albo Pretorio",
    )
    user_agent: str = Field(
        default="CivicResearchBot/1.1 (+contatto: tua-pec-o-email)",
        description="User agent string for HTTP requests",
    )
    delay: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Delay between requests in seconds",
    )
    timeout: int = Field(
        default=20,
        ge=5,
        le=120,
        description="HTTP request timeout in seconds",
    )
    max_pages: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="Maximum number of pages to scrape",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of retry attempts",
    )
    retry_backoff: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Backoff multiplier for retries",
    )

    model_config = ConfigDict(env_prefix="SCRAPER_")


class OCRConfig(BaseModel):
    """Configuration for OCR operations."""

    tesseract_cmd: Optional[str] = Field(
        default=None,
        description="Path to Tesseract executable (optional, auto-detected if not set)",
    )
    lang: str = Field(default="ita", description="OCR language code")
    psm: int = Field(
        default=3,
        ge=0,
        le=14,
        description="Page segmentation mode for Tesseract",
    )
    oem: int = Field(
        default=1,
        ge=0,
        le=3,
        description="OCR Engine Mode for Tesseract",
    )
    dpi: int = Field(
        default=300,
        ge=150,
        le=600,
        description="DPI for image preprocessing",
    )
    enable_preprocessing: bool = Field(
        default=True,
        description="Enable image preprocessing for better OCR accuracy",
    )

    model_config = ConfigDict(env_prefix="OCR_")


class LLMConfig(BaseModel):
    """Configuration for LLM operations."""

    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY"),
        description="Google API key for Gemini",
    )
    model_priority: List[str] = Field(
        default=["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"],
        description="Priority order for LLM models (failover)",
    )
    embedding_model_priority: List[str] = Field(
        default=["models/gemini-embedding-001", "models/text-embedding-004"],
        description="Priority order for embedding models",
    )
    use_gemini_by_default: bool = Field(
        default=False,
        description="Start RAG with Gemini active by default",
    )
    use_local_retriever_with_gemini: bool = Field(
        default=True,
        description="Use local retriever when FAISS index is missing",
    )
    max_tokens: int = Field(
        default=4096,
        ge=512,
        le=32768,
        description="Maximum tokens for LLM responses",
    )
    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM generation",
    )

    @field_validator("model_priority", "embedding_model_priority", mode="before")
    @classmethod
    def parse_priorities(cls, value):
        return _parse_list_env(value)

    model_config = ConfigDict(env_prefix="GOOGLE_")


class RAGConfig(BaseModel):
    """Configuration for RAG (Retrieval-Augmented Generation) operations."""

    chunk_size: int = Field(
        default=512,
        ge=128,
        le=2048,
        description="Size of text chunks for embedding",
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
        le=512,
        description="Overlap between chunks",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of top results to retrieve",
    )
    similarity_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold for retrieval",
    )
    enable_hybrid_search: bool = Field(
        default=True,
        description="Enable hybrid search (semantic + keyword)",
    )
    faiss_index_path: Optional[Path] = Field(
        default=None,
        description="Path to FAISS index file",
    )

    model_config = ConfigDict(env_prefix="RAG_")


class LoggingConfig(BaseModel):
    """Configuration for logging."""

    level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format",
    )
    file_path: Optional[Path] = Field(
        default=None,
        description="Path to log file (optional, console only if not set)",
    )
    max_file_size: int = Field(
        default=10485760,
        ge=1048576,
        le=104857600,
        description="Maximum log file size in bytes before rotation",
    )
    backup_count: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of backup log files to keep",
    )

    model_config = ConfigDict(env_prefix="LOG_")


class PerformanceConfig(BaseModel):
    """Configuration for performance optimizations."""

    enable_parallel_pdf: bool = Field(
        default=True,
        description="Enable parallel PDF extraction",
    )
    max_workers: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Maximum number of worker threads/processes",
    )
    batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Batch size for processing",
    )
    cache_enabled: bool = Field(
        default=True,
        description="Enable caching for expensive operations",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Cache time-to-live in seconds",
    )

    model_config = ConfigDict(env_prefix="PERF_")


class AppConfig(BaseModel):
    """Main application configuration combining all sub-configs."""

    scraper: ScraperConfig = Field(default_factory=ScraperConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)

    data_dir: Path = Field(default=Path("./data"), description="Directory for storing downloaded data")
    output_dir: Path = Field(default=Path("./output"), description="Directory for output files")
    cache_dir: Path = Field(default=Path("./cache"), description="Directory for cache files")

    @field_validator("data_dir", "output_dir", "cache_dir")
    @classmethod
    def ensure_directories(cls, value):
        if not value.exists():
            value.mkdir(parents=True, exist_ok=True)
        return value

    @classmethod
    def load_from_env(cls, env_file: Optional[Path] = None) -> "AppConfig":
        """Load configuration from environment variables and .env file."""
        if env_file:
            load_dotenv(env_file)
        else:
            for path in [Path(".env"), Path("../.env")]:
                if path.exists():
                    load_dotenv(path)
                    break

        llm_aliases = {
            "model_priority": ["GOOGLE_LLM_MODEL_PRIORITY", "GOOGLE_MODEL_PRIORITY"],
            "embedding_model_priority": [
                "GOOGLE_EMBEDDING_MODEL_PRIORITY",
                "GOOGLE_EMBED_MODEL_PRIORITY",
            ],
            "use_gemini_by_default": ["RAG_USE_GEMINI_BY_DEFAULT", "GOOGLE_USE_GEMINI_BY_DEFAULT"],
            "use_local_retriever_with_gemini": [
                "RAG_USE_LOCAL_RETRIEVER_WITH_GEMINI",
                "GOOGLE_USE_LOCAL_RETRIEVER_WITH_GEMINI",
            ],
        }

        return cls(
            scraper=_load_model_from_env(ScraperConfig, env_prefix="SCRAPER_"),
            ocr=_load_model_from_env(OCRConfig, env_prefix="OCR_"),
            llm=_load_model_from_env(LLMConfig, env_prefix="GOOGLE_", aliases=llm_aliases),
            rag=_load_model_from_env(RAGConfig, env_prefix="RAG_"),
            logging=_load_model_from_env(LoggingConfig, env_prefix="LOG_"),
            performance=_load_model_from_env(PerformanceConfig, env_prefix="PERF_"),
        )


def get_config() -> AppConfig:
    """Get application configuration singleton."""
    if not hasattr(get_config, "_config"):
        get_config._config = AppConfig.load_from_env()
    return get_config._config


if __name__ == "__main__":
    config = get_config()
    print("Configuration loaded successfully!")
    print(f"Data directory: {config.data_dir}")
    print(f"Logging level: {config.logging.level}")
    print(f"LLM models: {config.llm.model_priority}")
