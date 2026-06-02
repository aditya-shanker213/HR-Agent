"""
Core configuration using Pydantic BaseSettings.

Loads all environment variables from .env file.
Validates required variables at startup.
Fails loudly if any required variable is missing.

Pattern:
All services import settings from this file.
No service should load env vars directly.
"""

from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Required variables must be set in .env or environment.
    Application will refuse to start if any required variable is missing.
    """

    # -------------------------
    # Application settings
    # -------------------------
    APP_NAME: str = "HR AI Agent"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development, testing, staging, production
    TIMEZONE: str = "Asia/Kolkata"

    # API settings
    API_PREFIX: str = "/api/v1"
    FRONTEND_URL: str = "http://localhost:5173"

    # -------------------------
    # Server settings
    # -------------------------
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True

    # -------------------------
    # CORS settings
    # -------------------------
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5500"
    ALLOWED_METHODS: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    ALLOWED_HEADERS: str = "*"
    ALLOW_CREDENTIALS: bool = True

    # -------------------------
    # MongoDB settings
    # -------------------------
    MONGO_URI: str
    MONGO_DB_NAME: str = "hr_ai_agent"
    MONGO_MAX_POOL_SIZE: int = 50
    MONGO_MIN_POOL_SIZE: int = 10

    # -------------------------
    # Redis settings
    # -------------------------
    REDIS_URL: str
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_DECODE_RESPONSES: bool = False

    # -------------------------
    # JWT settings
    # -------------------------
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # -------------------------
    # OTP settings
    # -------------------------
    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RATE_LIMIT_MAX_REQUESTS: int = 3
    OTP_RATE_LIMIT_WINDOW_MINUTES: int = 15

    # -------------------------
    # Auth feature flags
    # -------------------------
    LOGIN_BY_EMAIL_ENABLED: bool = False
    CREATE_EMPLOYEE_PROFILE_ON_SIGNUP: bool = False

    # -------------------------
    # Email settings - SMTP
    # -------------------------
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_FROM_NAME: str = "HR AI Agent"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False

    # -------------------------
    # SendGrid settings
    # -------------------------
    SENDGRID_API_KEY: Optional[str] = None
    SENDGRID_FROM_EMAIL: Optional[str] = None

    # -------------------------
    # AI settings
    # -------------------------
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_TEMPERATURE: float = 0.7
    OPENAI_MAX_TOKENS: int = 1000

    # -------------------------
    # Vector DB settings
    # -------------------------
    VECTOR_DB_PROVIDER: str = "chromadb"
    VECTOR_DB_URL: Optional[str] = None
    VECTOR_DB_COLLECTION_NAME: str = "hr_policies"
    EMBEDDING_MODEL: str = "text-embedding-ada-002"

    # -------------------------
    # n8n webhook settings
    # -------------------------
    N8N_WEBHOOK_BASE_URL: Optional[str] = None
    N8N_LEAVE_APPROVAL_WEBHOOK: Optional[str] = None
    N8N_CLAIM_APPROVAL_WEBHOOK: Optional[str] = None
    N8N_ESCALATION_WEBHOOK: Optional[str] = None
    N8N_MANAGER_REMINDER_WEBHOOK: Optional[str] = None

    # -------------------------
    # Rate limiting
    # -------------------------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LEAVE_APPLICATIONS_PER_HOUR: int = 5
    RATE_LIMIT_CLAIM_SUBMISSIONS_PER_HOUR: int = 10
    RATE_LIMIT_CHAT_MESSAGES_PER_MINUTE: int = 20
    RATE_LIMIT_LOGIN_ATTEMPTS_PER_15_MINUTES: int = 5

    # -------------------------
    # File upload settings
    # -------------------------
    MAX_FILE_SIZE_MB: int = 5
    ALLOWED_FILE_EXTENSIONS: str = "pdf,jpg,jpeg,png"
    UPLOAD_DIR: str = "storage/uploads"

    # -------------------------
    # Security settings
    # -------------------------
    MAX_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCK_DURATION_MINUTES: int = 15
    STEP_UP_AUTH_EXPIRE_MINUTES: int = 10

    # -------------------------
    # Testing/Development flags
    # -------------------------
    EXPOSE_OTP_FOR_TESTING: bool = False
    SKIP_EMAIL_VERIFICATION: bool = False

    # -------------------------
    # Logging settings
    # -------------------------
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def get_cors_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS string into list."""
        if not self.ALLOWED_ORIGINS:
            return []
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    def get_cors_methods(self) -> list[str]:
        """Parse ALLOWED_METHODS string into list."""
        if not self.ALLOWED_METHODS:
            return []
        return [method.strip() for method in self.ALLOWED_METHODS.split(",") if method.strip()]

    def get_allowed_file_extensions(self) -> list[str]:
        """Parse ALLOWED_FILE_EXTENSIONS string into list."""
        if not self.ALLOWED_FILE_EXTENSIONS:
            return []
        return [ext.strip().lower() for ext in self.ALLOWED_FILE_EXTENSIONS.split(",") if ext.strip()]

    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

    def is_testing(self) -> bool:
        return self.ENVIRONMENT.lower() == "testing"

    def has_smtp_config(self) -> bool:
        """Check whether SMTP is configured."""
        return bool(
            self.SMTP_HOST
            and self.SMTP_USER
            and self.SMTP_PASSWORD
            and self.SMTP_FROM_EMAIL
        )

    def has_sendgrid_config(self) -> bool:
        """Check whether SendGrid is configured."""
        return bool(self.SENDGRID_API_KEY and self.SENDGRID_FROM_EMAIL)

    def has_email_provider(self) -> bool:
        """Check whether any email provider is available."""
        return self.has_smtp_config() or self.has_sendgrid_config()

    @model_validator(mode="after")
    def validate_settings(self):
        """
        Validate risky or conflicting settings.
        """
        if self.SMTP_USE_TLS and self.SMTP_USE_SSL:
            raise ValueError("SMTP_USE_TLS and SMTP_USE_SSL cannot both be True")

        if self.ACCESS_TOKEN_EXPIRE_MINUTES <= 0:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than 0")

        if self.REFRESH_TOKEN_EXPIRE_DAYS <= 0:
            raise ValueError("REFRESH_TOKEN_EXPIRE_DAYS must be greater than 0")

        if self.OTP_LENGTH < 4:
            raise ValueError("OTP_LENGTH should be at least 4 digits")

        if self.OTP_EXPIRE_MINUTES <= 0:
            raise ValueError("OTP_EXPIRE_MINUTES must be greater than 0")

        if self.is_production():
            if self.EXPOSE_OTP_FOR_TESTING:
                raise ValueError("EXPOSE_OTP_FOR_TESTING must be False in production")

            if self.SKIP_EMAIL_VERIFICATION:
                raise ValueError("SKIP_EMAIL_VERIFICATION must be False in production")

            if self.DEBUG:
                raise ValueError("DEBUG must be False in production")

            if len(self.JWT_SECRET) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in production")

            if not self.has_email_provider():
                raise ValueError("At least one email provider must be configured in production")

        return self


settings = Settings()