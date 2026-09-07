"""
Centralized application configuration.

All environment-driven settings are defined here using pydantic-settings.
Every other module in the application should import `settings` from this
file rather than reading os.environ directly, so configuration stays in
one place and is type-validated at startup.
"""
from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Application ---
    APP_NAME: str = "Enterprise Financial Document Intelligence"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Database ---
    DATABASE_URL: str = "postgresql://postgres:conan123@localhost:5342/EFDI"


    # --- Security / JWT ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- File Storage ---
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 25

    # --- Bulk Intake (Phase 10) ---
    # INTAKE_SCAN_DIR is the *only* directory the folder-scan intake
    # endpoint will ever read from. The API never accepts an arbitrary
    # filesystem path from the client -- only an optional relative
    # subpath *within* this configured root -- specifically so a
    # malicious or mistaken request can never be used to read files
    # from elsewhere on the server's disk. Kept separate from
    # UPLOAD_DIR (where accepted files are copied to) since intake is a
    # drop-off/staging location, distinct from permanent storage.
    INTAKE_SCAN_DIR: str = "intake"
    # Hard ceiling on how many files a single bulk-upload or folder-scan
    # request will process, regardless of how many are sent/found.
    # Protects against a single request tying up the server
    # indefinitely (e.g. someone uploading or pointing at a folder of
    # thousands of files) -- callers needing more should script
    # multiple requests rather than the server processing one giant one
    # synchronously.
    MAX_BULK_INTAKE_FILES: int = 100

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # --- OCR ---
    # Which engine app/ocr/factory.py uses when a request doesn't
    # explicitly specify one. "stub" is a safe, always-working default
    # for environments without network access to real model weights;
    # set to "paddleocr" or "easyocr" once weights are available.
    OCR_DEFAULT_ENGINE: str = "easyocr"

    # --- Extraction & LLM ---
    EXTRACTION_DEFAULT_ENGINE: str = "hybrid"
    LLM_PROVIDER: str = "mistral"
    EXTRACTION_LLM_MODEL: str = "mistral-small-2603"
    MISTRAL_API_KEY: str | None = None
    MISTRAL_API_BASE: str = "https://api.mistral.ai/v1"

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "testing"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}, got '{v}'")
        return v

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key_not_placeholder(cls, v: str) -> str:
        """
        Refuses to boot with the exact placeholder value shipped in
        .env.example -- a classic real-world deploy mistake is copying
        the example file and forgetting to actually change this one
        line, which would mean every JWT this server issues is
        forgeable by anyone who has read the (public) source code.
        Deliberately checks the literal placeholder string rather than
        e.g. "is this a known weak key" in general, since that's the
        one concrete, checkable mistake this can catch with certainty;
        a short-but-not-the-placeholder key is still allowed here
        (only checked strictly in production, see model_validator
        below) since dev/test environments legitimately want a
        throwaway key with no setup friction.
        """
        if v == "change-me-to-a-long-random-string-min-32-chars":
            raise ValueError(
                "SECRET_KEY is still set to the placeholder value from .env.example. "
                "Generate a real one, e.g.: openssl rand -hex 32"
            )
        return v

    @model_validator(mode="after")
    def validate_production_secret_key_strength(self) -> "Settings":
        """
        Production gets a stricter length check than dev/test --
        enforced here (not in the field_validator above) specifically
        so it can see APP_ENV, which isn't available to a single-field
        validator running in field-declaration order.
        """
        if self.is_production and len(self.SECRET_KEY) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters in production. "
                "Generate one with: openssl rand -hex 32"
            )
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor.

    lru_cache ensures the .env file is parsed once per process, not on
    every import or every request.
    """
    return Settings()


settings = get_settings()
