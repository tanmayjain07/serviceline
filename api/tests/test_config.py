"""Configuration parsing.

These exist because a settings error is uniquely nasty: it is raised at import
time, before logging is configured, so it surfaces in production as a container
that exits immediately with no useful message.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

REQUIRED = {
    "database_url": "postgresql+psycopg://u:p@localhost/db",
    "database_admin_url": "postgresql+psycopg://o:p@localhost/db",
    "jwt_secret": "test-secret",
}


def build(**overrides: object) -> Settings:
    return Settings(**{**REQUIRED, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The format the documentation shows.
        ('["https://app.example.com"]', ["https://app.example.com"]),
        # A single bare origin -- what most people type first.
        ("https://app.example.com", ["https://app.example.com"]),
        # Comma-separated, with the spacing a human would use.
        (
            "https://a.example.com, https://b.example.com",
            ["https://a.example.com", "https://b.example.com"],
        ),
        # JSON array with several entries.
        (
            '["https://a.example.com", "https://b.example.com"]',
            ["https://a.example.com", "https://b.example.com"],
        ),
        # Empty means no cross-origin callers, not a crash.
        ("", []),
    ],
)
def test_cors_origins_accepts_the_formats_people_actually_type(
    raw: str, expected: list[str]
) -> None:
    assert build(cors_origins=raw).cors_origins == expected


def test_trailing_slashes_are_stripped() -> None:
    """A browser's Origin header never has a trailing slash.

    Leaving one in the configured value produces a CORS failure that works
    perfectly from curl, which is a genuinely difficult afternoon.
    """
    settings = build(cors_origins="https://app.example.com/")
    assert settings.cors_origins == ["https://app.example.com"]


def test_malformed_json_says_what_is_wrong() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        build(cors_origins='["https://app.example.com"')


def test_json_that_is_not_an_array_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be an array"):
        build(cors_origins='{"origin": "https://app.example.com"}')


def test_default_is_the_local_dev_server() -> None:
    assert build().cors_origins == ["http://localhost:5173"]
