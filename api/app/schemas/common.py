"""Shared response shapes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """Base for schemas read directly from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    """A page of results.

    `total` is the count *after* row-level security has been applied, so it is
    the number of rows this caller may see -- never a global count that would
    leak the size of another tenant's data.
    """

    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class Message(BaseModel):
    detail: str
