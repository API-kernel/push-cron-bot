import asyncio
import aiosqlite

DB_PATH = "bot.db"

async def migrate():
    print(f"🔄 Миграция на независимые ссылки (Snapshot)...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Создаем новую таблицу
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shared_links (
                token TEXT PRIMARY KEY,
                cron_expression TEXT,
                message_text TEXT,
                content_type TEXT,
                file_id TEXT
            )
        """)
        print("✅ Таблица shared_links создана.")

        # 2. (Опционально) Можно удалить колонку share_link_token из tasks, 
        # но SQLite не поддерживает DROP COLUMN в старых версиях легко.
        # Просто оставим её, она больше не будет использоваться.

if __name__ == "__main__":
    asyncio.run(migrate())