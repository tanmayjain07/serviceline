"""Application configuration, loaded from the environment."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Two connection strings on purpose.
    #
    # database_url uses the low-privilege application role. It is NOT the owner
    # of any table and does not have BYPASSRLS, so row-level security applies to
    # it with no exceptions. Everything the API does at runtime goes through it.
    #
    # database_admin_url uses the owning role and is used ONLY by Alembic
    # migrations and the test harness. Keeping them separate is what makes the
    # isolation guarantee real -- a table's owner silently bypasses RLS unless
    # FORCE ROW LEVEL SECURITY is set, so we both use a separate role and force
    # the policies. Belt and braces.
    database_url: str
    database_admin_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14

    invite_expiry_days: int = 7
    trial_days: int = 14

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    sql_echo: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
