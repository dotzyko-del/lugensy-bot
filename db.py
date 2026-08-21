import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import uuid

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import Client as FirestoreClient

import config

# Инициализация Firebase
if config.FIREBASE_CREDENTIALS_JSON:
    cred_dict = json.loads(config.FIREBASE_CREDENTIALS_JSON)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate(config.FIREBASE_CREDENTIALS_PATH)

firebase_admin.initialize_app(cred)

db: FirestoreClient = firestore.client()

# Коллекции
USERS_COLLECTION = "users"
TRACKS_COLLECTION = "tracks"
CONFIG_COLLECTION = "config"
ADMIN_CHAT_DOC_ID = "admin_chat"

def _to_datetime(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    return ts.to_datetime().replace(tzinfo=timezone.utc)

async def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    doc_ref = db.collection(USERS_COLLECTION).document(str(telegram_id))
    doc = await asyncio.to_thread(doc_ref.get)
    if doc.exists:
        data = doc.to_dict()
        data['telegram_id'] = int(doc.id)
        data['manager_ids'] = [int(m) for m in data.get('manager_ids', [])]
        data['created_at'] = _to_datetime(data.get('created_at'))
        return data
    return None

async def create_user(telegram_id: int, username: str = "", role: str = "user") -> None:
    doc_ref = db.collection(USERS_COLLECTION).document(str(telegram_id))
    await asyncio.to_thread(doc_ref.set, {
        'telegram_id': telegram_id,
        'username': username,
        'role': role,
        'manager_ids': [],
        'created_at': firestore.SERVER_TIMESTAMP,
    }, merge=True)

async def update_user(telegram_id: int, data: Dict[str, Any]) -> None:
    doc_ref = db.collection(USERS_COLLECTION).document(str(telegram_id))
    await asyncio.to_thread(doc_ref.update, data)

async def get_all_admins() -> List[Dict[str, Any]]:
    users_ref = db.collection(USERS_COLLECTION)
    query = users_ref.where('role', 'in', ['admin', 'superadmin'])
    docs = await asyncio.to_thread(query.stream)
    admins = []
    for doc in docs:
        data = doc.to_dict()
        data['telegram_id'] = int(doc.id)
        admins.append(data)
    return admins

async def get_track(track_id: str) -> Optional[Dict[str, Any]]:
    doc_ref = db.collection(TRACKS_COLLECTION).document(track_id)
    doc = await asyncio.to_thread(doc_ref.get)
    if doc.exists:
        data = doc.to_dict()
        data['id'] = doc.id
        data['user_id'] = int(data.get('user_id', 0))
        data['file_size'] = int(data.get('file_size', 0))
        data['artists'] = data.get('artists', [])
        data['music_authors'] = data.get('music_authors', [])
        data['created_at'] = _to_datetime(data.get('created_at'))
        data['submitted_at'] = _to_datetime(data.get('submitted_at'))
        data['reviewed_at'] = _to_datetime(data.get('reviewed_at'))
        data['expires_at'] = _to_datetime(data.get('expires_at'))
        data['reminded_at'] = _to_datetime(data.get('reminded_at'))
        return data
    return None

async def create_track(data: Dict[str, Any]) -> str:
    track_id = str(uuid.uuid4())
    doc_ref = db.collection(TRACKS_COLLECTION).document(track_id)
    await asyncio.to_thread(doc_ref.set, data)
    return track_id

async def update_track(track_id: str, data: Dict[str, Any]) -> None:
    doc_ref = db.collection(TRACKS_COLLECTION).document(track_id)
    await asyncio.to_thread(doc_ref.update, data)

async def delete_track(track_id: str) -> None:
    doc_ref = db.collection(TRACKS_COLLECTION).document(track_id)
    await asyncio.to_thread(doc_ref.delete)

async def list_tracks_by_user(user_id: int) -> List[Dict[str, Any]]:
    tracks_ref = db.collection(TRACKS_COLLECTION)
    query = tracks_ref.where('user_id', '==', user_id)
    docs = await asyncio.to_thread(query.stream)
    tracks = []
    for doc in docs:
        data = doc.to_dict()
        data['id'] = doc.id
        data['user_id'] = int(data.get('user_id', 0))
        data['artists'] = data.get('artists', [])
        data['music_authors'] = data.get('music_authors', [])
        data['created_at'] = _to_datetime(data.get('created_at'))
        data['expires_at'] = _to_datetime(data.get('expires_at'))
        tracks.append(data)
    tracks.sort(key=lambda x: x.get('created_at') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return tracks

async def list_tracks_by_status(statuses: List[str]) -> List[Dict[str, Any]]:
    tracks_ref = db.collection(TRACKS_COLLECTION)
    query = tracks_ref.where('status', 'in', statuses)
    docs = await asyncio.to_thread(query.stream)
    tracks = []
    for doc in docs:
        data = doc.to_dict()
        data['id'] = doc.id
        data['user_id'] = int(data.get('user_id', 0))
        data['artists'] = data.get('artists', [])
        data['music_authors'] = data.get('music_authors', [])
        data['created_at'] = _to_datetime(data.get('created_at'))
        data['expires_at'] = _to_datetime(data.get('expires_at'))
        tracks.append(data)
    tracks.sort(key=lambda x: x.get('created_at') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return tracks

async def get_admin_chat_id() -> Optional[int]:
    doc_ref = db.collection(CONFIG_COLLECTION).document(ADMIN_CHAT_DOC_ID)
    doc = await asyncio.to_thread(doc_ref.get)
    if doc.exists:
        return int(doc.to_dict().get('chat_id', 0))
    return None

async def set_admin_chat_id(chat_id: int) -> None:
    doc_ref = db.collection(CONFIG_COLLECTION).document(ADMIN_CHAT_DOC_ID)
    await asyncio.to_thread(doc_ref.set, {'chat_id': chat_id})

async def check_title_unique(user_id: int, title: str, exclude_track_id: Optional[str] = None) -> bool:
    tracks_ref = db.collection(TRACKS_COLLECTION)
    query = tracks_ref.where('user_id', '==', user_id).where('title', '==', title)
    docs = await asyncio.to_thread(query.stream)
    for doc in docs:
        if exclude_track_id and doc.id == exclude_track_id:
            continue
        return False
    return True