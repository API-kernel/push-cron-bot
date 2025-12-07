import asyncio
import aiosqlite

DB_PATH = "bot.db"

async def migrate():
    print(f"🔄 Начинаю миграцию {DB_PATH}...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # Добавляем колонку is_active (Boolean), по умолчанию True (1)
            # Чтобы все старые задачи остались активными
            await db.execute("ALTER TABLE tasks ADD COLUMN is_active BOOLEAN DEFAULT 1")
            await db.commit()
            print("✅ Успешно: Колонка 'is_active' добавлена.")
        except Exception as e:
            if "duplicate column name" in str(e):
                print("ℹ️ Колонка 'is_active' уже существует. Миграция не требуется.")
            else:
                print(f"❌ Ошибка миграции: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())