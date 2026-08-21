import asyncio
import io
import httpx
from typing import Optional
from supabase import create_client, Client

import config

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
            file_options={"content-type": "audio/mpeg", "upsert": "true"}
        )
        return True
    except Exception as e:
        print(f"Upload error: {e}")
        return False

async def delete_file(object_key: str) -> bool:
    try:
        await asyncio.to_thread(
            get_supabase().storage.from_(config.SUPABASE_BUCKET).remove,
            [object_key]
        )
        return True
    except Exception as e:
        print(f"Delete error: {e}")
        return False

async def get_file_bytes(object_key: str) -> Optional[bytes]:
    try:
        result = await asyncio.to_thread(
            get_supabase().storage.from_(config.SUPABASE_BUCKET).download,
            object_key
        )
        if result is None:
            print(f"Download returned None for {object_key}")
            return None
        return result
    except Exception as e:
        print(f"Download error for {object_key}: {e}")
        return None

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
        print(f"Signed URL response: {result}")
        return None
    except Exception as e:
        print(f"Signed URL error for {object_key}: {e}")
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
    except Exception as e:
        print(f"HTTP download error for {object_key}: {e}")
        return None