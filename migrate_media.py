import asyncio
import aiosqlite
DB_PATH = "bot.db"

async def migrate():
    print(f"🔄 Начинаю медиа-миграцию {DB_PATH}...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # 1. Добавляем content_type (по умолчанию 'text')
            await db.execute("ALTER TABLE tasks ADD COLUMN content_type TEXT DEFAULT 'text'")
            print("✅ Колонка 'content_type' добавлена.")
        except Exception as e:
            if "duplicate" in str(e): print("ℹ️ 'content_type' уже есть.")
            else: print(f"❌ Ошибка content_type: {e}")

        try:
            # 2. Добавляем file_id (может быть NULL)
            await db.execute("ALTER TABLE tasks ADD COLUMN file_id TEXT")
            print("✅ Колонка 'file_id' добавлена.")
        except Exception as e:
            if "duplicate" in str(e): print("ℹ️ 'file_id' уже есть.")
            else: print(f"❌ Ошибка file_id: {e}")
            
        await db.commit()

if __name__ == "__main__":
    asyncio.run(migrate())