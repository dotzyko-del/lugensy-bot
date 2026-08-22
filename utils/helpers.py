import io
import logging
from typing import Optional
from aiogram.types import BufferedInputFile
import db
import storage

logger = logging.getLogger(__name__)

def get_status_emoji(status: str) -> str:
    mapping = {
        'pending_data': '🕒',
        'data_filled': '📝',
        'submitted': '⏳',
        'rejected': '❌',
        'approved': '✅'
    }
    return mapping.get(status, '❔')

def format_track_message(track: dict, show_status: bool = False) -> str:
    lines = []
    if track.get('title'):
        lines.append(f"Название: {track['title']}")
    else:
        lines.append("Название: не указано")
    if track.get('artists'):
        lines.append(f"Исполнители: {', '.join(track['artists'])}")
    if track.get('music_authors'):
        lines.append(f"Авторы музыки: {', '.join(track['music_authors'])}")
    if track.get('wav_link'):
        lines.append(f"Ссылка на WAV: {track['wav_link']}")
    if show_status:
        status_str = {
            'pending_data': 'Данные не заполнены',
            'data_filled': 'Данные заполнены',
            'submitted': 'На проверке',
            'rejected': 'Отклонён',
            'approved': 'Одобрен'
        }.get(track.get('status'), track.get('status'))
        lines.append(f"Статус: {status_str}")
        if track.get('expires_at'):
            lines.append(f"Срок хранения: {track['expires_at'].strftime('%Y-%m-%d %H:%M')}")
        if track.get('comment'):
            lines.append(f"Комментарий: {track['comment']}")
    return "\n".join(lines)

async def get_track_audio(track: dict) -> Optional[BufferedInputFile]:
    if not track.get('object_key'):
        logger.warning(f"No object_key in track: {track.get('id')}")
        return None
    
    file_bytes = await storage.get_file_bytes(track['object_key'])
    if file_bytes is None:
        logger.warning(f"Direct download failed for {track['object_key']}, trying signed URL fallback...")
        file_bytes = await storage.download_via_signed_url(track['object_key'])
    
    if file_bytes:
        return BufferedInputFile(file_bytes, filename=track.get('original_filename', 'audio.mp3'))
    
    logger.error(f"All download methods failed for {track['object_key']}")
    return None