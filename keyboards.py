from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_track_actions_keyboard(track_id: str, status: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status in ['pending_data', 'data_filled', 'rejected']:
        builder.button(text="✏️ Заполнить/Изменить", callback_data=f"edit_track:{track_id}")
    if status == 'data_filled':
        builder.button(text="📤 Отправить на проверку", callback_data=f"submit_track:{track_id}")
    if status == 'submitted':
        builder.button(text="🔙 Отозвать", callback_data=f"withdraw_track:{track_id}")
    if status in ['pending_data', 'data_filled', 'rejected']:
        builder.button(text="🗑 Удалить", callback_data=f"delete_track:{track_id}")
    if status != 'approved' and not status.startswith('pending'):
        builder.button(text="⏳ Продлить (+3 дня)", callback_data=f"extend_track:{track_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_pagination_keyboard(items: list, page: int, total_pages: int, prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        text = item.get('display_text', '')
        builder.button(text=text, callback_data=f"{prefix}:{item['id']}:{page}")
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"page:{prefix}:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"page:{prefix}:{page+1}"))
    builder.row(*nav_buttons)
    return builder.as_markup()

def get_admin_review_keyboard(track_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Одобрить", callback_data=f"approve:{track_id}")
    builder.button(text="❌ Отклонить", callback_data=f"reject:{track_id}")
    builder.adjust(2)
    return builder.as_markup()