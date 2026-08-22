import asyncio
import io
import logging
import httpx
from typing import Optional
from supabase import create_client, Client

import config

logger = logging.getLogger(__name__)

_supabase: Optional[Client] = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _supabase

async def upload_file(file_bytes: bytes, object_key: str) -> bool:
    try:
        await asyncio.to_thread(
            get_supabase().storage.from_(config.SUPABASE_BUCKET).upload,
            path=object_key,
            file=file_bytes,
            # Supabase Storage only honors the "x-upsert" header (sent as a
            # lowercase string). "upsert" (without the x- prefix) is silently
            # ignored, so re-uploading to an existing object_key returns a
            # 400 "Asset already exists" error.
            file_options={"content-type": "audio/mpeg", "x-upsert": "true"}
        )
        return True
    except Exception:
        logger.exception(f"Upload error for {object_key}")
        return False

async def delete_file(object_key: str) -> bool:
    try:
        await asyncio.to_thread(
            get_supabase().storage.from_(config.SUPABASE_BUCKET).remove,
            [object_key]
        )
        return True
    except Exception:
        logger.exception(f"Delete error for {object_key}")
        return False

async def get_file_bytes(object_key: str) -> Optional[bytes]:
    try:
        result = await asyncio.to_thread(
            get_supabase().storage.from_(config.SUPABASE_BUCKET).download,
            object_key
        )
        if result is None:
            logger.warning(f"Download returned None for {object_key}")
            return None
        return result
    except Exception:
        logger.exception(f"Download error for {object_key}")
    return await download_via_signed_url(object_key)

async def get_signed_url(object_key: str, expires_in: int = 3600) -> Optional[str]:
    """Get a signed URL for downloading the file (fallback method)."""
    try:
        result = await asyncio.to_thread(
            get_supabase().storage.from_(config.SUPABASE_BUCKET).create_signed_url,
            object_key,
            expires_in
        )
        if result and result.get("signedURL"):
            return result["signedURL"]
        if result and result.get("signedUrl"):
            return result["signedUrl"]
        logger.warning(f"Unexpected signed URL response for {object_key}: {result}")
        return None
    except Exception:
        logger.exception(f"Signed URL error for {object_key}")
        return None

async def download_via_signed_url(object_key: str) -> Optional[bytes]:
    """Download file using signed URL as fallback."""
    signed_url = await get_signed_url(object_key)
    if not signed_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(signed_url)
            response.raise_for_status()
            return response.content
    except Exception:
        logger.exception(f"HTTP download error for {object_key}")
        return None
