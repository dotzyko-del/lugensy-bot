import asyncio
import io
from typing import Optional
from supabase import create_client, Client

import config

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)

async def upload_file(file_bytes: bytes, object_key: str) -> None:
    await asyncio.to_thread(
        supabase.storage.from_(config.SUPABASE_BUCKET).upload,
        path=object_key,
        file=file_bytes,
        file_options={"content-type": "audio/mpeg"}
    )

async def delete_file(object_key: str) -> None:
    await asyncio.to_thread(
        supabase.storage.from_(config.SUPABASE_BUCKET).remove,
        [object_key]
    )

async def get_file_bytes(object_key: str) -> Optional[bytes]:
    try:
        return await asyncio.to_thread(
            supabase.storage.from_(config.SUPABASE_BUCKET).download,
            object_key
        )
    except Exception as e:
        print(f"Download error: {e}")
        return None