import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        enable_decoding=False,
    )

    environment: str = "development"
    app_name: str = "VIGE API"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_docs_enabled: bool = True
    database_url: str = "sqlite:///./vige.db"
    upload_dir: str = "./uploads"
    output_dir: str = "./outputs"
    frontend_base_url: str = "http://localhost:3000"
    cors_allowed_origins: list[str] = ["http://localhost:3000"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1"]
    force_https_redirect: bool = False
    max_pdfs_per_batch: int = 70
    upload_chunk_size_bytes: int = 1024 * 1024
    redis_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_worker_concurrency: int = 8
    auth_jwt_secret_key: str = "change-me-in-production"
    auth_jwt_algorithm: str = "HS256"
    auth_access_token_expire_minutes: int = 60
    auth_password_reset_expire_minutes: int = 30
    auth_debug_return_reset_token: bool = False
    auth_allowed_emails: list[str] = []

    @field_validator("cors_allowed_origins", "trusted_hosts", "auth_allowed_emails", mode="before")
    @classmethod
    def parse_csv_or_list(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    decoded = json.loads(raw)
                    if isinstance(decoded, list):
                        return [str(item).strip() for item in decoded if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            items = [item.strip().strip("\"'") for item in raw.split(",") if item.strip()]
            return items
        return value

    @field_validator("cors_allowed_origins", mode="after")
    @classmethod
    def normalize_origins(cls, value: list[str]) -> list[str]:
        return [item.rstrip("/") for item in value]

    @field_validator("auth_allowed_emails", mode="after")
    @classmethod
    def normalize_allowed_emails(cls, value: list[str]) -> list[str]:
        return [item.strip().lower() for item in value if item.strip()]

    @field_validator("environment", mode="after")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()


settings = Settings()
