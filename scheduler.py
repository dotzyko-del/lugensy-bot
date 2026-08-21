import asyncio
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from google.cloud import firestore

import db
import storage

bot = None  # будет установлен в setup_scheduler

async def check_expired_tracks():
    now = datetime.now(timezone.utc)
    tracks = await db.list_tracks_by_status(['pending_data', 'data_filled', 'submitted', 'rejected'])
    for track in tracks:
        expires = track.get('expires_at')
        if expires and expires <= now:
            object_key = track.get('object_key')
            if object_key:
                await storage.delete_file(object_key)
            await db.delete_track(track['id'])
            try:
                await bot.send_message(
                    track['user_id'],
                    f"🕒 Ваш трек «{track.get('title', track.get('original_filename', 'Без названия'))}» был автоматически удалён, так как истёк срок хранения."
                )
            except Exception as e:
                print(f"Error notifying user: {e}")

async def send_reminders():
    now = datetime.now(timezone.utc)
    reminder_time = now + timedelta(hours=24)
    tracks = await db.list_tracks_by_status(['pending_data', 'data_filled', 'submitted', 'rejected'])
    for track in tracks:
        expires = track.get('expires_at')
        if expires and expires <= reminder_time and not track.get('reminded_at'):
            try:
                text = f"⏰ Напоминание: срок хранения трека «{track.get('title', track.get('original_filename', 'Без названия'))}» истечёт через 24 часа."
                if track['status'] == 'pending_data':
                    text += "\nЗаполните данные или продлите срок."
                await bot.send_message(track['user_id'], text)
                await db.update_track(track['id'], {'reminded_at': firestore.SERVER_TIMESTAMP})
            except Exception as e:
                print(f"Error sending reminder: {e}")

def setup_scheduler(bot_instance):
    global bot
    bot = bot_instance
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(check_expired_tracks, IntervalTrigger(minutes=30), id='check_expired', replace_existing=True)
    scheduler.add_job(send_reminders, IntervalTrigger(minutes=30), id='send_reminders', replace_existing=True)
    return scheduler