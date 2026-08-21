import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import config
import handlers
from scheduler import setup_scheduler

async def main():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            TimedRotatingFileHandler(config.LOG_FILE, when="midnight", backupCount=1, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)

    scheduler = setup_scheduler()
    # Установка команд бота
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="mytracks", description="Мои треки"),
        BotCommand(command="filldata", description="Заполнить данные"),
        BotCommand(command="submit", description="Отправить на проверку"),
        BotCommand(command="edit", description="Изменить трек"),
        BotCommand(command="delete", description="Удалить трек"),
    ])
    scheduler.start()

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())