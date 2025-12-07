import asyncio
import aiosqlite
import uuid

DB_PATH = "bot.db"

async def migrate():
    print(f"🔄 Миграция токенов шаринга...")
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # 1. Добавляем колонку
            await db.execute("ALTER TABLE tasks ADD COLUMN share_link_token TEXT")
            print("✅ Колонка share_link_token добавлена.")
        except Exception as e:
            print(f"ℹ️ Колонка уже есть или ошибка: {e}")

        # 2. Генерируем токены для старых задач (где NULL)
        cursor = await db.execute("SELECT id FROM tasks WHERE share_link_token IS NULL")
        rows = await cursor.fetchall()
        
        if rows:
            print(f"🛠 Генерирую токены для {len(rows)} задач...")
            for (task_id,) in rows:
                token = str(uuid.uuid4())[:8] # Берем короткий токен (8 символов), этого хватит
                await db.execute("UPDATE tasks SET share_link_token = ? WHERE id = ?", (token, task_id))
            await db.commit()
            print("✅ Токены сгенерированы.")
        else:
            print("👌 Все задачи уже имеют токены.")

if __name__ == "__main__":
    asyncio.run(migrate())