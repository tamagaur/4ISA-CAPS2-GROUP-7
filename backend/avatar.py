"""
backend.avatar — profile-picture upload: validate, re-encode, store.

DESIGN CONSTRAINT: the Supabase project is on the free plan and was at 4.63 of
5 GB monthly egress when this was written. Image bytes are never stored in
Postgres and never served through the API from the database — only this
module's output (a 128x128 WebP, ~6 KB) ever leaves the server, and it goes to
Supabase Storage, not a column. avatar_path (migration 0059) holds only the
resulting object's path.

The re-encode is also what strips EXIF: a phone photo commonly carries GPS
coordinates, and Image.save() for WEBP writes none unless an exif= kwarg is
passed, which nothing here does.
"""
from __future__ import annotations

import io
import logging
import os
import secrets
from typing import BinaryIO

import httpx
from fastapi import HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB
# Bounds the DECODED buffer, not the upload. A highly compressed file can
# declare huge pixel dimensions in its header and still be a few KB on the
# wire -- the 2 MB cap above never sees that. 20 MP is generous for a real
# phone photo (which gets cropped to 128x128 anyway).
MAX_AVATAR_PIXELS = 20_000_000
AVATAR_SIZE = (128, 128)
AVATAR_BUCKET = "avatars"
_READ_CHUNK = 65536

# Pillow's own default ceiling (~89.5M px) only *warns* (via warnings.warn,
# which doesn't stop execution) below 2x that figure, and only raises
# DecompressionBombError above it. Pin Pillow's own ceiling to ours so that
# gap closes too, in addition to the explicit check in to_avatar_webp below.
Image.MAX_IMAGE_PIXELS = MAX_AVATAR_PIXELS


def read_capped(stream: BinaryIO, limit: int = MAX_AVATAR_BYTES) -> bytes:
    """Reads `stream` in chunks, raising 413 the moment `limit` is crossed
    instead of buffering an arbitrarily large upload into memory first."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Image must be 2 MB or smaller.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def to_avatar_webp(data: bytes) -> bytes:
    """Decodes `data` as an image (never trusting a client-supplied
    Content-Type or filename) and re-encodes it to a 128x128 WebP, cropped to
    a centered square. Raises 400 if it doesn't decode as an image at all."""
    try:
        probe = Image.open(io.BytesIO(data))
        # Dimensions come from the header, decoded before any pixel data --
        # check them BEFORE verify()/decode so a small file declaring an
        # enormous image is rejected without ever allocating that buffer.
        width, height = probe.size
        if width * height > MAX_AVATAR_PIXELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That image's dimensions are too large.",
            )
        probe.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That file isn't a valid image.",
        ) from exc

    # verify() leaves the Image unusable for anything further; re-open fresh.
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # honor orientation before the EXIF block is dropped
    img = img.convert("RGB")
    img = ImageOps.fit(img, AVATAR_SIZE, Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="WEBP", quality=80)
    return out.getvalue()


def public_url(object_name: str | None) -> str | None:
    """The browser-facing URL for `object_name` in the avatars bucket, or
    None when there is no picture (object_name is None) or SUPABASE_URL
    isn't set. Built from the environment, never hardcoded and never baked
    into a frontend file -- the frontend only ever sees this already-
    resolved URL, in UserOut.avatar_url / MeResponse.avatar_url."""
    if object_name is None:
        return None
    url = os.environ.get("SUPABASE_URL")
    if not url:
        return None
    return f"{url.rstrip('/')}/storage/v1/object/public/{AVATAR_BUCKET}/{object_name}"


def new_object_name(user_id: int) -> str:
    """Server-generated object name — never any part of the client's
    filename, so a user can't path-traverse or collide another account's
    object."""
    return f"{user_id}/{secrets.token_hex(16)}.webp"


def upload(object_name: str, data: bytes) -> None:
    """Puts `data` at `object_name` in the `avatars` Storage bucket, via the
    Storage REST API with the service-role key (never the client, never the
    anon key — this must be able to write to any user's folder)."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to upload avatars."
        )
    resp = httpx.put(
        f"{url.rstrip('/')}/storage/v1/object/{AVATAR_BUCKET}/{object_name}",
        content=data,
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": "image/webp",
            "x-upsert": "true",
        },
        timeout=10.0,
    )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not save the picture. Please try again.",
        )


def delete(object_name: str) -> None:
    """Deletes `object_name` from the `avatars` Storage bucket. Best-effort:
    called after a user's avatar_path is overwritten, to not leak the old
    object against the Storage quota -- but a failed delete must not fail
    the upload that replaced it, so this only logs."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.warning("Could not delete old avatar %s: Supabase env vars not set.", object_name)
        return
    try:
        resp = httpx.delete(
            f"{url.rstrip('/')}/storage/v1/object/{AVATAR_BUCKET}/{object_name}",
            headers={"Authorization": f"Bearer {key}", "apikey": key},
            timeout=10.0,
        )
        if resp.status_code >= 400:
            logger.warning(
                "Could not delete old avatar %s: Storage returned %s.", object_name, resp.status_code
            )
    except httpx.HTTPError:
        logger.warning("Could not delete old avatar %s: request failed.", object_name, exc_info=True)
