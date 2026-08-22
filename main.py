import asyncio
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, Update
from aiohttp import web

import config
import handlers
import db
from scheduler import setup_scheduler

logger = logging.getLogger(__name__)


async def set_commands(bot: Bot):
    # Общие команды
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="mytracks", description="Мои треки"),
        BotCommand(command="filldata", description="Заполнить данные"),
        BotCommand(command="submit", description="Отправить на проверку"),
        BotCommand(command="edit", description="Изменить трек"),
        BotCommand(command="delete", description="Удалить трек"),
    ])

    # Админские команды для каждого администратора
    admins = await db.get_all_admins()
    admin_commands = [
        BotCommand(command="alltracks", description="Список треков"),
        BotCommand(command="addadmin", description="Добавить админа"),
        BotCommand(command="removeadmin", description="Убрать админа"),
        BotCommand(command="setmanager", description="Назначить менеджера"),
        BotCommand(command="unsetmanager", description="Убрать менеджера"),
        BotCommand(command="setadminchat", description="Установить чат"),
    ]
    for admin in admins:
        try:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin['telegram_id'])
            )
        except Exception:
            logger.exception(f"Failed to set admin commands for {admin['telegram_id']}")


async def handle_webhook(request):
    bot = request.app["bot"]
    dp = request.app["dp"]

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})

    await dp.feed_webhook_update(bot, update)

    return web.Response(status=200, text="OK")


async def on_startup(app: web.Application):
    bot = app["bot"]
    scheduler = app["scheduler"]

    await set_commands(bot)
    scheduler.start()

    # NOTE: WEBHOOK_URL must be the bare host (e.g. https://your-app.onrender.com),
    # WEBHOOK_PATH ("/webhook") is appended here to match the route registered below.
    webhook_url = f"{config.WEBHOOK_URL}{config.WEBHOOK_PATH}"
    logger.info(f"Setting webhook to {webhook_url}...")
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logger.info("Webhook set successfully")


async def on_shutdown(app: web.Application):
    bot = app["bot"]
    scheduler = app["scheduler"]

    logger.info("Shutting down...")
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        logger.exception("Failed to delete webhook")

    try:
        scheduler.shutdown()
    except Exception:
        logger.exception("Failed to stop scheduler")

    await bot.session.close()
    logger.info("Shutdown complete")


def setup_logging():
    handlers_list = [
        # Explicit stdout, line-buffered by the logging module itself
        # (StreamHandler flushes on every emitted record), so this always
        # reaches Render's Logs tab regardless of PYTHONUNBUFFERED.
        logging.StreamHandler(stream=sys.stdout)
    ]

    # File logging only makes sense for local development - Render's
    # filesystem is ephemeral and you can't browse it without shell access.
    # Skip it in production (Render sets the RENDER env var automatically).
    if not os.getenv("RENDER"):
        os.makedirs("logs", exist_ok=True)
        handlers_list.append(
            TimedRotatingFileHandler(
                config.LOG_FILE,
                when="midnight",
                backupCount=1,
                encoding="utf-8"
            )
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers_list,
    )


def main():
    setup_logging()

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)

    scheduler = setup_scheduler(bot)

    if config.WEBHOOK_URL:
        app = web.Application()

        app["bot"] = bot
        app["dp"] = dp
        app["scheduler"] = scheduler

        app.router.add_post(config.WEBHOOK_PATH, handle_webhook)
        app.on_startup.append(on_startup)
        app.on_shutdown.append(on_shutdown)

        logger.info("Starting webhook server...")
        web.run_app(app, host="0.0.0.0", port=int(config.PORT))
    else:
        logger.info("Starting polling...")
        asyncio.run(run_polling(bot, dp, scheduler))


async def run_polling(bot, dp, scheduler):
    await set_commands(bot)
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        scheduler.shutdown()


if __name__ == "__main__":
    main()
