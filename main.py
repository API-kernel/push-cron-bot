import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from middlewares import AdminOnlyMiddleware
from services.cron_manager import scheduler, restore_tasks
from database.base import init_db
from handlers import router

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.message.middleware(AdminOnlyMiddleware())
    dp.include_router(router)

    await init_db()
    scheduler.start()
    await restore_tasks(bot)

    # --- УСТАНОВКА МЕНЮ КОМАНД ---
    commands = [
        BotCommand(command="list", description="📋 Управление задачами"),
        BotCommand(command="add", description="✨ Создать задачу"),
        BotCommand(command="timezone", description="🌍 Часовой пояс"),
        BotCommand(command="export", description="📤 Бэкап (Экспорт)"),
        BotCommand(command="import", description="📥 Загрузка (Импорт)"),
        BotCommand(command="help", description="ℹ️ Справка"),
    ]
    
    await bot.set_my_commands(commands)
    # -----------------------------

    print("🤖 Бот запущен...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
