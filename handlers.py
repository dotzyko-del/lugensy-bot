import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.enums import ContentType
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from google.cloud import firestore

import config
import db
import storage
import keyboards
import states
from utils import helpers

router = Router()


def safe_text(message: Message) -> Optional[str]:
    return message.text.strip() if message.text else None


async def is_admin(telegram_id: int) -> bool:
    if telegram_id == config.TELEGRAM_ADMIN_ID:
        return True
    user = await db.get_user(telegram_id)
    return bool(user and user.get("role") in ["admin", "superadmin"])


async def is_superadmin(telegram_id: int) -> bool:
    if telegram_id == config.TELEGRAM_ADMIN_ID:
        return True
    user = await db.get_user(telegram_id)
    return bool(user and user.get("role") == "superadmin")


async def send_track_to_review(bot: Bot, track_id: str):
    track = await db.get_track(track_id)
    if not track:
        return

    user = await db.get_user(track["user_id"])
    if not user:
        return

    manager_ids = user.get("manager_ids", [])
    text = helpers.format_track_message(track)
    markup = keyboards.get_admin_review_keyboard(track_id)

    if manager_ids:
        messages = []
        for mgr_id in manager_ids:
            try:
                audio_for_manager = await helpers.get_track_audio(track)
                if audio_for_manager:
                    msg = await bot.send_audio(mgr_id, audio=audio_for_manager, caption=text, reply_markup=markup)
                else:
                    msg = await bot.send_message(mgr_id, text + "\n(Аудиофайл недоступен)", reply_markup=markup)
                messages.append({"chat_id": mgr_id, "message_id": msg.message_id})
            except Exception as e:
                print(f"Failed to send to manager {mgr_id}: {e}")
        if messages:
            await db.update_track(track_id, {"review_messages": messages})
    else:
        admin_chat_id = await db.get_admin_chat_id()
        if not admin_chat_id:
            admin_chat_id = config.TELEGRAM_ADMIN_ID
        try:
            audio_for_chat = await helpers.get_track_audio(track)
            if audio_for_chat:
                msg = await bot.send_audio(admin_chat_id, audio=audio_for_chat, caption=text, reply_markup=markup)
            else:
                msg = await bot.send_message(admin_chat_id, text + "\n(Аудиофайл недоступен)", reply_markup=markup)
            await db.update_track(track_id, {"review_messages": [{"chat_id": admin_chat_id, "message_id": msg.message_id}]})
        except Exception as e:
            print(f"Failed to send to admin chat: {e}")


async def delete_review_messages(bot: Bot, track: dict):
    messages = track.get("review_messages", [])
    for msg_info in messages:
        try:
            await bot.delete_message(chat_id=msg_info["chat_id"], message_id=msg_info["message_id"])
        except Exception:
            pass
    await db.update_track(track["id"], {"review_messages": []})


@router.message(Command("help"))
async def cmd_help(message: Message):
    user = await db.get_user(message.from_user.id)
    role = user.get("role") if user else "user"
    text = "📋 Список доступных команд:\n\n"
    if role in ["admin", "superadmin"] or message.from_user.id == config.TELEGRAM_ADMIN_ID:
        text += "👑 Админ-команды:\n"
        text += "/alltracks - список треков (на проверке/одобренные)\n"
        text += "/addadmin - назначить админа\n"
        text += "/removeadmin - убрать админа\n"
        text += "/setmanager - назначить менеджера\n"
        text += "/unsetmanager - убрать менеджера\n"
        text += "/setadminchat - установить общий чат\n\n"
    text += "👤 Пользовательские команды:\n"
    text += "/start - приветствие\n"
    text += "/mytracks - мои треки\n"
    text += "/filldata - заполнить данные\n"
    text += "/submit - отправить на проверку\n"
    text += "/edit - изменить трек\n"
    text += "/delete - удалить трек\n"
    text += "/help - эта справка\n"
    await message.answer(text)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if not user:
        role = "superadmin" if message.from_user.id == config.TELEGRAM_ADMIN_ID else "user"
        await db.create_user(message.from_user.id, message.from_user.username or "", role)
        await message.answer("Добро пожаловать! Отправьте аудиофайл MP3, чтобы начать.")
    else:
        await message.answer("С возвращением! Отправьте аудиофайл MP3 или используйте /mytracks.")


@router.message(F.content_type == ContentType.STICKER)
async def handle_sticker(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await message.answer("Сейчас нужен текст или MP3-файл, а не стикер.")
    else:
        await message.answer("Стикеры пока не поддерживаются. Отправь MP3-файл или команду.")


@router.message(F.content_type.in_({ContentType.AUDIO, ContentType.DOCUMENT}))
async def handle_audio(message: Message):
    if message.audio:
        if message.audio.mime_type != "audio/mpeg":
            await message.answer("Поддерживаются только MP3 файлы.")
            return
    elif message.document:
        if not message.document.file_name or not message.document.file_name.lower().endswith(".mp3"):
            await message.answer("Поддерживаются только MP3 файлы.")
            return
    else:
        await message.answer("Отправьте аудиофайл MP3.")
        return

    file_id = message.audio.file_id if message.audio else message.document.file_id
    file_name = message.audio.file_name if message.audio else message.document.file_name
    file_size = message.audio.file_size if message.audio else message.document.file_size

    if file_size and file_size > 20 * 1024 * 1024:
        await message.answer("Файл слишком большой (максимум 20 МБ).")
        return

    try:
        file = await message.bot.get_file(file_id)
        file_bytes = await message.bot.download_file(file.file_path)
    except Exception as e:
        print(f"Download error: {e}")
        await message.answer("Не удалось скачать файл.")
        return

    object_key = f"tracks/{file_id}.mp3"
    upload_success = await storage.upload_file(file_bytes.read(), object_key)
    if not upload_success:
        await message.answer("Не удалось загрузить файл в хранилище. Попробуйте ещё раз позже.")
        return

    track_data = {
        "user_id": message.from_user.id,
        "file_id": file_id,
        "object_key": object_key,
        "file_type": "mp3",
        "file_size": file_size,
        "original_filename": file_name or f"{file_id}.mp3",
        "title": None,
        "artists": [],
        "music_authors": [],
        "wav_link": None,
        "status": "pending_data",
        "created_at": firestore.SERVER_TIMESTAMP,
        "submitted_at": None,
        "reviewed_at": None,
        "reviewed_by": None,
        "comment": "",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "extended_once": False,
        "reminded_at": None,
        "review_messages": [],
    }
    track_id = await db.create_track(track_data)
    await message.answer(
        f"Аудио получено. ID трека: {track_id}\nУ вас есть 7 дней, чтобы заполнить данные. Используйте /filldata {track_id} или /mytracks."
    )


@router.message(Command("filldata"))
async def cmd_filldata(message: Message, state: FSMContext):
    text = safe_text(message)
    if not text:
        await message.answer("Укажите ID трека: /filldata <ID>")
        return
    args = text.split()
    if len(args) < 2:
        await message.answer("Укажите ID трека: /filldata <ID>")
        return
    track_id = args[1]
    track = await db.get_track(track_id)
    if not track or track["user_id"] != message.from_user.id:
        await message.answer("Трек не найден или не принадлежит вам.")
        return
    if track["status"] == "approved":
        await message.answer("Одобренные треки нельзя изменять.")
        return
    await state.set_state(states.FillData.waiting_for_title)
    await state.update_data(track_id=track_id, edit_mode=False)
    await message.answer("Введите название трека:")


@router.message(StateFilter(states.FillData.waiting_for_title))
async def process_title(message: Message, state: FSMContext):
    title = safe_text(message)
    if not title:
        await message.answer("Нужен текст. Введите название трека сообщением.")
        return
    data = await state.get_data()
    track_id = data["track_id"]
    user_id = message.from_user.id
    unique = await db.check_title_unique(user_id, title, exclude_track_id=track_id)
    if not unique:
        await state.update_data(pending_title=title)
        await state.set_state(states.FillData.confirm_overwrite)
        await message.answer(
            f"У вас уже есть трек с названием «{title}».\n"
            "Вы можете перезаписать его новыми данными (старый трек будет удалён, таймер нового трека будет сброшен на 7 дней).\n"
            "Перезаписать? (да/нет)"
        )
        return
    await state.update_data(title=title)
    await state.set_state(states.FillData.waiting_for_artists)
    await message.answer("Введите исполнителей (через запятую, можно пусто):")


@router.message(StateFilter(states.FillData.confirm_overwrite))
async def process_overwrite(message: Message, state: FSMContext):
    answer = safe_text(message)
    if not answer:
        await message.answer("Ответьте текстом: да или нет.")
        return
    answer = answer.lower()
    data = await state.get_data()
    track_id = data["track_id"]
    pending_title = data.get("pending_title")
    if answer in ["да", "yes", "y"]:
        old_tracks = await db.list_tracks_by_user(message.from_user.id)
        for old_track in old_tracks:
            if old_track.get("title") == pending_title and old_track["id"] != track_id:
                if old_track.get("object_key"):
                    try:
                        await storage.delete_file(old_track["object_key"])
                    except Exception as e:
                        print(f"Delete storage error: {e}")
                await db.delete_track(old_track["id"])
                break
        await state.update_data(title=pending_title, overwrite_done=True)
        await state.set_state(states.FillData.waiting_for_artists)
        await message.answer("Старый трек удалён. Введите исполнителей (через запятую, можно пусто):")
    else:
        await state.set_state(states.FillData.waiting_for_title)
        await message.answer("Введите другое название:")


@router.message(StateFilter(states.FillData.waiting_for_artists))
async def process_artists(message: Message, state: FSMContext):
    artists_text = safe_text(message)
    if artists_text is None:
        await message.answer("Нужен текстовый ответ. Введите исполнителей сообщением.")
        return
    artists = [a.strip() for a in artists_text.split(",") if a.strip()]
    await state.update_data(artists=artists)
    await state.set_state(states.FillData.waiting_for_music_authors)
    await message.answer("Введите авторов музыки (через запятую, можно пусто):")


@router.message(StateFilter(states.FillData.waiting_for_music_authors))
async def process_music_authors(message: Message, state: FSMContext):
    authors_text = safe_text(message)
    if authors_text is None:
        await message.answer("Нужен текстовый ответ. Введите авторов музыки сообщением.")
        return
    authors = [a.strip() for a in authors_text.split(",") if a.strip()]
    await state.update_data(music_authors=authors)
    await state.set_state(states.FillData.waiting_for_wav_link)
    await message.answer("Введите ссылку на WAV файл (или '-' чтобы пропустить):")


@router.message(StateFilter(states.FillData.waiting_for_wav_link))
async def process_wav_link(message: Message, state: FSMContext):
    link = safe_text(message)
    if link is None:
        await message.answer("Нужен текстовый ответ. Введите ссылку или '-'.")
        return
    if link == "-":
        link = None
    data = await state.get_data()
    track_id = data["track_id"]
    update_data = {
        "title": data["title"],
        "artists": data["artists"],
        "music_authors": data["music_authors"],
        "wav_link": link,
        "status": "data_filled",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=3),
        "extended_once": False,
        "reminded_at": None,
    }
    await db.update_track(track_id, update_data)
    await state.clear()
    await message.answer(
        "Данные сохранены. Трек теперь в статусе «Данные заполнены».\n"
        "Вы можете отправить его на проверку командой /submit или /mytracks."
    )


@router.message(Command("submit"))
async def cmd_submit(message: Message):
    text = safe_text(message)
    if not text:
        await message.answer("Укажите ID трека: /submit <ID>")
        return
    args = text.split()
    if len(args) < 2:
        await message.answer("Укажите ID трека: /submit <ID>")
        return
    track_id = args[1]
    track = await db.get_track(track_id)
    if not track or track["user_id"] != message.from_user.id:
        await message.answer("Трек не найден или не принадлежит вам.")
        return
    if track["status"] not in ["data_filled", "rejected"]:
        await message.answer("Трек нельзя отправить на проверку из текущего статуса.")
        return
    await db.update_track(track_id, {
        "status": "submitted",
        "submitted_at": firestore.SERVER_TIMESTAMP,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=3),
        "reminded_at": None,
    })
    await send_track_to_review(message.bot, track_id)
    await message.answer("Трек отправлен на проверку.")


@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext):
    text = safe_text(message)
    if not text:
        await message.answer("Укажите ID трека: /edit <ID>")
        return
    args = text.split()
    if len(args) < 2:
        await message.answer("Укажите ID трека: /edit <ID>")
        return
    track_id = args[1]
    track = await db.get_track(track_id)
    if not track or track["user_id"] != message.from_user.id:
        await message.answer("Трек не найден или не принадлежит вам.")
        return
    if track["status"] == "approved":
        await message.answer("Одобренные треки нельзя редактировать.")
        return
    if track["status"] == "submitted":
        await delete_review_messages(message.bot, track)
        await db.update_track(track_id, {"status": "data_filled", "expires_at": datetime.now(timezone.utc) + timedelta(days=3)})
    await state.set_state(states.EditData.waiting_for_choice)
    await state.update_data(track_id=track_id)
    await message.answer("Что вы хотите изменить?\n1. Аудиофайл\n2. Название\n3. Исполнителей\n4. Авторов музыки\n5. Ссылку на WAV\nОтправьте номер или текст:")


@router.message(StateFilter(states.EditData.waiting_for_choice))
async def process_edit_choice(message: Message, state: FSMContext):
    choice = safe_text(message)
    if not choice:
        await message.answer("Нужен текстовый ответ: номер или название пункта.")
        return
    choice = choice.lower()
    if choice in ["1", "аудиофайл"]:
        await state.set_state(states.EditData.waiting_for_file)
        await message.answer("Отправьте новый аудиофайл MP3.")
    elif choice in ["2", "название"]:
        await state.set_state(states.EditData.waiting_for_title)
        await message.answer("Введите новое название:")
    elif choice in ["3", "исполнителей"]:
        await state.set_state(states.EditData.waiting_for_artists)
        await message.answer("Введите новых исполнителей (через запятую):")
    elif choice in ["4", "авторов музыки"]:
        await state.set_state(states.EditData.waiting_for_music_authors)
        await message.answer("Введите новых авторов музыки (через запятую):")
    elif choice in ["5", "ссылку на wav", "ссылка на wav", "wav"]:
        await state.set_state(states.EditData.waiting_for_wav_link)
        await message.answer("Введите новую ссылку на WAV (или '-' для удаления):")
    else:
        await message.answer("Неверный выбор. Попробуйте ещё раз.")


@router.message(StateFilter(states.EditData.waiting_for_file), F.content_type.in_({ContentType.AUDIO, ContentType.DOCUMENT}))
async def process_edit_file(message: Message, state: FSMContext):
    data = await state.get_data()
    track_id = data["track_id"]

    if message.audio:
        if message.audio.mime_type != "audio/mpeg":
            await message.answer("Поддерживаются только MP3 файлы.")
            return
    elif message.document:
        if not message.document.file_name or not message.document.file_name.lower().endswith(".mp3"):
            await message.answer("Поддерживаются только MP3 файлы.")
            return

    file_id = message.audio.file_id if message.audio else message.document.file_id
    file_name = message.audio.file_name if message.audio else message.document.file_name
    file_size = message.audio.file_size if message.audio else message.document.file_size
    if file_size and file_size > 20 * 1024 * 1024:
        await message.answer("Файл слишком большой (максимум 20 МБ).")
        return

    try:
        file = await message.bot.get_file(file_id)
        file_bytes = await message.bot.download_file(file.file_path)
    except Exception as e:
        print(f"Download error on edit: {e}")
        await message.answer("Не удалось скачать файл.")
        return

    old_track = await db.get_track(track_id)
    if old_track and old_track.get("object_key"):
        try:
            await storage.delete_file(old_track["object_key"])
        except Exception as e:
            print(f"Delete old file error: {e}")

    new_object_key = f"tracks/{file_id}.mp3"
    upload_success = await storage.upload_file(file_bytes.read(), new_object_key)
    if not upload_success:
        await message.answer("Не удалось загрузить новый файл в хранилище.")
        return

    await db.update_track(track_id, {
        "file_id": file_id,
        "object_key": new_object_key,
        "original_filename": file_name or f"{file_id}.mp3",
        "file_size": file_size,
        "status": "data_filled",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=3)
    })
    await message.answer("Файл обновлён.")
    await state.clear()


@router.message(StateFilter(states.EditData.waiting_for_file))
async def process_edit_file_fallback(message: Message):
    await message.answer("Сейчас ожидаю MP3-файл как аудио или документ.")


@router.message(StateFilter(states.EditData.waiting_for_title))
async def process_edit_title(message: Message, state: FSMContext):
    title = safe_text(message)
    if not title:
        await message.answer("Нужен текст. Введите новое название сообщением.")
        return
    data = await state.get_data()
    track_id = data["track_id"]
    unique = await db.check_title_unique(message.from_user.id, title, exclude_track_id=track_id)
    if not unique:
        await message.answer("Название занято. Выберите другое.")
        return
    await db.update_track(track_id, {"title": title, "status": "data_filled", "expires_at": datetime.now(timezone.utc) + timedelta(days=3)})
    await message.answer("Название обновлено.")
    await state.clear()


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    text = safe_text(message)
    if not text:
        await message.answer("Укажите ID трека: /delete <ID>")
        return
    args = text.split()
    if len(args) < 2:
        await message.answer("Укажите ID трека: /delete <ID>")
        return
    track_id = args[1]
    track = await db.get_track(track_id)
    if not track or track["user_id"] != message.from_user.id:
        await message.answer("Трек не найден или не принадлежит вам.")
        return
    if track["status"] == "approved":
        await message.answer("Одобренные треки нельзя удалить.")
        return
    if track.get("object_key"):
        try:
            await storage.delete_file(track["object_key"])
        except Exception as e:
            print(f"Delete track storage error: {e}")
    await db.delete_track(track_id)
    await message.answer("Трек удалён.")


@router.message(Command("mytracks"))
async def cmd_mytracks(message: Message):
    tracks = await db.list_tracks_by_user(message.from_user.id)
    if not tracks:
        await message.answer("У вас нет треков.")
        return
    page = 0
    total_pages = (len(tracks) + 6) // 7
    start = page * 7
    end = start + 7
    page_tracks = tracks[start:end]
    display_items = []
    for t in page_tracks:
        status_emoji = helpers.get_status_emoji(t["status"])
        display_text = f"{status_emoji} {t.get('title') or t.get('original_filename')}"
        if t.get("artists"):
            display_text = f"{status_emoji} {', '.join(t['artists'])} - {t.get('title', '')}"
        display_items.append({"id": t["id"], "display_text": display_text, "track": t})
    markup = keyboards.get_pagination_keyboard(display_items, page, total_pages, prefix="mytrack")
    await message.answer("Ваши треки:", reply_markup=markup)


@router.callback_query(F.data.startswith("mytrack:"))
async def process_mytrack_click(callback: CallbackQuery):
    parts = callback.data.split(":")
    track_id = parts[1]
    track = await db.get_track(track_id)
    if not track or track["user_id"] != callback.from_user.id:
        await callback.answer("Трек не найден.")
        return
    text = helpers.format_track_message(track, show_status=True)
    text += f"\nID трека: {track['id']}"
    audio_file = await helpers.get_track_audio(track)
    if audio_file:
        await callback.message.answer_audio(audio=audio_file, caption=text)
    else:
        await callback.message.answer(text)
    await callback.answer()


@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    text = safe_text(message)
    if not text:
        await message.answer("Укажите Telegram ID: /addadmin <ID>")
        return
    args = text.split()
    if len(args) < 2:
        await message.answer("Укажите Telegram ID: /addadmin <ID>")
        return
    admin_id = int(args[1])
    user = await db.get_user(admin_id)
    if user:
        await db.update_user(admin_id, {"role": "admin"})
    else:
        await db.create_user(admin_id, "", "admin")
    await message.answer(f"Пользователь {admin_id} назначен администратором.")


@router.message(Command("removeadmin"))
async def cmd_removeadmin(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    text = safe_text(message)
    if not text:
        await message.answer("Укажите Telegram ID: /removeadmin <ID>")
        return
    args = text.split()
    if len(args) < 2:
        await message.answer("Укажите Telegram ID: /removeadmin <ID>")
        return
    admin_id = int(args[1])
    user = await db.get_user(admin_id)
    if user and user["role"] == "admin":
        await db.update_user(admin_id, {"role": "user"})
        await message.answer("Администратор удалён.")
    else:
        await message.answer("Администратор не найден.")


@router.message(Command("setmanager"))
async def cmd_setmanager(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    text = safe_text(message)
    if not text:
        await message.answer("Использование: /setmanager <user_id> <admin_id>")
        return
    args = text.split()
    if len(args) < 3:
        await message.answer("Использование: /setmanager <user_id> <admin_id>")
        return
    user_id = int(args[1])
    admin_id = int(args[2])
    user = await db.get_user(user_id)
    admin = await db.get_user(admin_id)
    if not user or not admin:
        await message.answer("Пользователь или админ не найден.")
        return
    if admin["role"] not in ["admin", "superadmin"]:
        await message.answer("Указанный ID не является администратором.")
        return
    managers = set(user.get("manager_ids", []))
    managers.add(admin_id)
    await db.update_user(user_id, {"manager_ids": list(managers)})
    await message.answer(f"Менеджер {admin_id} назначен пользователю {user_id}.")


@router.message(Command("unsetmanager"))
async def cmd_unsetmanager(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    text = safe_text(message)
    if not text:
        await message.answer("Использование: /unsetmanager <user_id> <admin_id>")
        return
    args = text.split()
    if len(args) < 3:
        await message.answer("Использование: /unsetmanager <user_id> <admin_id>")
        return
    user_id = int(args[1])
    admin_id = int(args[2])
    user = await db.get_user(user_id)
    if user:
        managers = set(user.get("manager_ids", []))
        managers.discard(admin_id)
        await db.update_user(user_id, {"manager_ids": list(managers)})
        await message.answer("Менеджер удалён.")
    else:
        await message.answer("Пользователь не найден.")


@router.message(Command("setadminchat"))
async def cmd_setadminchat(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    if message.reply_to_message:
        chat_id = message.reply_to_message.chat.id
    else:
        text = safe_text(message)
        if not text:
            await message.answer("Используйте команду в ответе на сообщение из нужного чата или укажите ID: /setadminchat <ID>")
            return
        args = text.split()
        if len(args) < 2:
            await message.answer("Используйте команду в ответе на сообщение из нужного чата или укажите ID: /setadminchat <ID>")
            return
        chat_id = int(args[1])
    await db.set_admin_chat_id(chat_id)
    await message.answer(f"Общий чат установлен: {chat_id}")


@router.callback_query(F.data.startswith("approve:"))
async def process_approve(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.")
        return
    track_id = callback.data.split(":")[1]
    track = await db.get_track(track_id)
    if not track or track["status"] != "submitted":
        await callback.answer("Трек уже обработан.")
        return
    await db.update_track(track_id, {
        "status": "approved",
        "reviewed_at": firestore.SERVER_TIMESTAMP,
        "reviewed_by": callback.from_user.id,
        "expires_at": None,
        "reminded_at": None,
    })
    await callback.bot.send_message(
        track["user_id"],
        f"✅ Ваш трек «{track.get('title', track.get('original_filename', ''))}» одобрен!"
    )
    try:
        await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n✅ Одобрено")
    except Exception:
        pass
    await callback.answer("Одобрено!")


@router.callback_query(F.data.startswith("reject:"))
async def process_reject_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.")
        return
    track_id = callback.data.split(":")[1]
    track = await db.get_track(track_id)
    if not track or track["status"] != "submitted":
        await callback.answer("Трек уже обработан.")
        return
    await state.set_state(states.RejectTrack.waiting_for_comment)
    await state.update_data(track_id=track_id, message_id=callback.message.message_id, chat_id=callback.message.chat.id)
    await callback.message.answer("Введите комментарий для отклонения:")
    await callback.answer()


@router.message(StateFilter(states.RejectTrack.waiting_for_comment))
async def process_reject_comment(message: Message, state: FSMContext):
    comment = safe_text(message)
    if not comment:
        await message.answer("Нужен текстовый комментарий.")
        return
    data = await state.get_data()
    track_id = data["track_id"]
    track = await db.get_track(track_id)
    await db.update_track(track_id, {
        "status": "rejected",
        "reviewed_at": firestore.SERVER_TIMESTAMP,
        "reviewed_by": message.from_user.id,
        "comment": comment,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=3),
        "reminded_at": None,
    })
    await message.bot.send_message(
        track["user_id"],
        f"❌ Ваш трек «{track.get('title', track.get('original_filename', ''))}» отклонён.\nКомментарий: {comment}"
    )
    try:
        await message.bot.edit_message_caption(
            chat_id=data["chat_id"],
            message_id=data["message_id"],
            caption=(track.get("title", "") or "") + f"\n\n❌ Отклонено: {comment}"
        )
    except Exception:
        pass
    await message.answer("Трек отклонён.")
    await state.clear()


@router.message(Command("alltracks"))
async def cmd_alltracks(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    statuses = ["submitted", "approved"]
    tracks = await db.list_tracks_by_status(statuses)
    if not tracks:
        await message.answer("Нет треков.")
        return
    page = 0
    total_pages = (len(tracks) + 6) // 7
    start = page * 7
    end = start + 7
    page_tracks = tracks[start:end]
    display_items = []
    for t in page_tracks:
        status_emoji = helpers.get_status_emoji(t["status"])
        display_text = f"{status_emoji} {t.get('title') or t.get('original_filename')} (user: {t['user_id']})"
        display_items.append({"id": t["id"], "display_text": display_text})
    markup = keyboards.get_pagination_keyboard(display_items, page, total_pages, prefix="alltrack")
    await message.answer("Все треки (submitted/approved):", reply_markup=markup)


@router.callback_query(F.data.startswith("alltrack:"))
async def process_alltrack_click(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.")
        return
    parts = callback.data.split(":")
    track_id = parts[1]
    track = await db.get_track(track_id)
    if not track:
        await callback.answer("Трек не найден.")
        return
    text = helpers.format_track_message(track, show_status=True)
    audio_file = await helpers.get_track_audio(track)
    if audio_file:
        await callback.message.answer_audio(audio=audio_file, caption=text)
    else:
        await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.startswith("page:"))
async def process_pagination(callback: CallbackQuery):
    parts = callback.data.split(":")
    prefix = parts[1]
    page = int(parts[2])
    if prefix == "mytrack":
        tracks = await db.list_tracks_by_user(callback.from_user.id)
    elif prefix == "alltrack":
        if not await is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.")
            return
        tracks = await db.list_tracks_by_status(["submitted", "approved"])
    else:
        await callback.answer("Неизвестный тип.")
        return
    total_pages = (len(tracks) + 6) // 7
    if page < 0 or page >= total_pages:
        page = 0
    start = page * 7
    end = start + 7
    page_tracks = tracks[start:end]
    display_items = []
    for t in page_tracks:
        status_emoji = helpers.get_status_emoji(t["status"])
        display_text = f"{status_emoji} {t.get('title') or t.get('original_filename')}"
        if prefix == "alltrack":
            display_text += f" (user: {t['user_id']})"
        display_items.append({"id": t["id"], "display_text": display_text})
    markup = keyboards.get_pagination_keyboard(display_items, page, total_pages, prefix=prefix)
    await callback.message.edit_reply_markup(reply_markup=markup)
    await callback.answer()


@router.message()
async def fallback_message(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == states.EditData.waiting_for_file.state:
        await message.answer("Сейчас ожидаю MP3-файл.")
        return
    if current_state:
        await message.answer("Неподдерживаемый формат. Отправьте текстовое сообщение.")
        return
    await message.answer("Поддерживаются команды, текст и MP3-файлы.")
