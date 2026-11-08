"""Settings loaded from the process environment (and `.env` when present).

Secrets live only here and in `.env`; never log a Settings instance.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    # Object storage for raw payloads. Locally this is the MinIO root user from docker-compose.
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_bucket: str = "stockiq-raw"
    minio_root_user: str = ""
    minio_root_password: SecretStr = SecretStr("")

    # SEC fair access: a descriptive User-Agent that includes a contact address.
    sec_user_agent: str = ""

    openfigi_api_key: SecretStr = SecretStr("")
    massive_api_key: SecretStr = SecretStr("")

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
