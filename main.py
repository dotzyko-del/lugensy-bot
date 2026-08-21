import asyncio
import logging
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
        BotCommand(command="removeadmin", description="Удалить админа"),
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
        except Exception as e:
            print(f"Failed to set admin commands for {admin['telegram_id']}: {e}")

async def on_startup(app):
    bot = app['bot']
    # Установка вебхука
    webhook_url = f"{config.WEBHOOK_URL}{config.WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    await set_commands(bot)
    print(f"Webhook set to {webhook_url}")

async def on_shutdown(app):
    bot = app['bot']
    await bot.delete_webhook()
    await bot.session.close()

# async def handle_webhook(request):
#     bot = request.app['bot']
#     dp = request.app['dp']
#     data = await request.json()
#     update = Update.model_validate(data, context={"bot": bot})
#     await dp.feed_webhook_update(update)
#     return web.Response()

async def handle_webhook(request):
    bot = request.app["bot"]
    dp = request.app["dp"]

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})

    await dp.feed_webhook_update(bot, update)

    return web.Response(status=200, text="OK")


def main():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            TimedRotatingFileHandler(
                config.LOG_FILE,
                when="midnight",
                backupCount=1,
                encoding="utf-8"
            ),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)

    scheduler = setup_scheduler(bot)

    if config.WEBHOOK_URL:
        app = web.Application()

        app["bot"] = bot
        app["dp"] = dp
        app["scheduler"] = scheduler
        app["logger"] = logger

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


async def on_startup(app: web.Application):
    bot = app["bot"]
    scheduler = app["scheduler"]
    logger = app["logger"]

    await set_commands(bot)
    scheduler.start()

    logger.info("Setting webhook...")
    await bot.set_webhook(
        url=config.WEBHOOK_URL,
        drop_pending_updates=True
    )
    logger.info("Webhook set successfully")


async def on_shutdown(app: web.Application):
    bot = app["bot"]
    scheduler = app["scheduler"]
    logger = app["logger"]

    logger.info("Shutting down...")
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        logger.exception("Failed to delete webhook: %s", e)

    try:
        scheduler.shutdown()
    except Exception as e:
        logger.exception("Failed to stop scheduler: %s", e)

    await bot.session.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()