"""Shapes for GET /auth/me and the /admin permission endpoints (the API
contract in Yuan's permissions proposal)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from backend import avatar


class MeResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: str
    permissions: list[str]  # effective keys, sorted
    # The My profile page (backend/profile.py): the account's picture as a
    # Supabase Storage path (never image bytes — migration 0059/0060), and
    # whether this server can store one.
    avatar_path: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def avatar_url(self) -> str | None:
        """The full public URL for avatar_path, same derivation as
        UserOut.avatar_url (backend/avatar.py.public_url) -- null whenever
        avatar_path is. Never stored, never hardcoded: built from
        SUPABASE_URL at response time."""
        return avatar.public_url(self.avatar_path)

    profile_pictures: bool = False


class ProfileUpdate(BaseModel):
    """PATCH /auth/me body: a field left out is unchanged; avatar_data_url
    null removes the picture. The picture is still sent as a data URL (same
    shape the browser already produces) but is never stored as one — it is
    decoded, validated, resized and put in Supabase Storage like POST
    /users/me/avatar, and only its resulting path is kept (backend/profile.py
    decode_avatar_data_url, backend/avatar.py). Anything else is refused (422)."""
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
