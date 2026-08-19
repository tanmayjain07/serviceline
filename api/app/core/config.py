"""Application configuration, loaded from the environment."""

import json
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # NoDecode turns off pydantic-settings' automatic JSON decoding for this
    # field so the validator below sees the raw string.
    #
    # Without it, a perfectly reasonable CORS_ORIGINS of
    # "https://example.com" fails at import time with
    #     SettingsError: error parsing value for field "cors_origins"
    # because the value is not valid JSON. That message names neither the
    # offending variable's value nor the expected format, and it kills the
    # process before any logging is configured -- so it surfaces as a container
    # that dies on boot for no visible reason. Accepting the obvious formats is
    # cheaper than making everyone learn that CORS_ORIGINS must be JSON.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    sql_echo: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        """Accept a JSON array, a comma-separated list, or a single origin."""
        if value is None:
            return []
        if isinstance(value, list):
            return [cls._normalise_origin(str(item)) for item in value]
        if not isinstance(value, str):
            return value

        text = value.strip()
        if not text:
            return []

        # Anything opening with a JSON bracket is treated as JSON. Catching '{'
        # as well as '[' matters: an object would otherwise fall through to the
        # comma-splitting branch and be accepted as a single literal origin,
        # which then silently matches nothing.
        if text.startswith(("[", "{")):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"CORS_ORIGINS looks like JSON but is not valid JSON: "
                    f"{exc}. Either fix the JSON or use a plain "
                    f"comma-separated list."
                ) from None
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS as JSON must be an array of strings")
            return [cls._normalise_origin(str(item)) for item in parsed]

        return [cls._normalise_origin(part) for part in text.split(",") if part.strip()]

    @staticmethod
    def _normalise_origin(raw: str) -> str:
        """Trim whitespace and any trailing slash.

        A browser sends `Origin: https://example.com` with no trailing slash, so
        a configured value of `https://example.com/` never matches and every
        request fails CORS while working fine from curl. Normalising here means
        the trailing slash simply stops mattering.
        """
        return raw.strip().rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
