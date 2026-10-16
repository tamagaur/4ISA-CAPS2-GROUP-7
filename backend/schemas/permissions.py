"""Shapes for GET /auth/me and the /admin permission endpoints (the API
contract in Yuan's permissions proposal)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class MeResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: str
    permissions: list[str]  # effective keys, sorted
    # The My profile page (backend/profile.py): the account's picture as a
    # data URL, and whether this server can store one (migration 0058).
    avatar_data_url: str | None = None
    profile_pictures: bool = False


class ProfileUpdate(BaseModel):
    """PATCH /auth/me body: a field left out is unchanged; avatar_data_url
    null removes the picture. Anything else is refused (422)."""
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    avatar_data_url: str | None = None


class CatalogEntry(BaseModel):
    key: str
    label: str
    group: str
    description: str


class CatalogResponse(BaseModel):
    permissions: list[CatalogEntry]
    # {"admin": "all", "staff": [...]}
    roles: dict[str, str | list[str]]


class UserPermissions(BaseModel):
    user_id: int
    role: str
    overrides: dict[str, bool]  # only what differs from the role's preset
    permissions: list[str]      # effective keys, sorted


class UserPermissionsUpdate(BaseModel):
    """PUT body. `overrides` may list keys equal to the preset; they are
    dropped, so what is stored is only the differences."""
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "staff"]
    overrides: dict[str, bool] = {}
