# Single source of truth for bot commands.
# Used by:
#   - handlers.cmd_help()      -> builds the /help text
#   - main.set_commands()      -> builds Telegram's native "/" command menu
#
# Keeping this in one place means /help and the "/" menu can never
# silently drift apart from each other.

# (command_without_slash, description)
USER_COMMANDS = [
    ("start", "Начать"),
    ("help", "Помощь"),
    ("mytracks", "Мои треки"),
    ("filldata", "Заполнить данные (укажите ID трека)"),
    ("submit", "Отправить на проверку (укажите ID трека)"),
    ("edit", "Изменить трек (укажите ID трека)"),
    ("delete", "Удалить трек (укажите ID трека)"),
]

ADMIN_COMMANDS = [
    ("alltracks", "Список треков"),
    ("addadmin", "Назначить админа"),
    ("removeadmin", "Убрать админа"),
    ("setmanager", "Назначить менеджера"),
    ("unsetmanager", "Убрать менеджера"),
    ("setadminchat", "Установить общий чат"),
]


def format_command_list(commands: list[tuple[str, str]]) -> str:
    return "\n".join(f"/{cmd} — {desc}" for cmd, desc in commands)
