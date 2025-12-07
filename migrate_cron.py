import asyncio
import aiosqlite

DB_PATH = "bot.db"

DOW_MAP = {
    '0': 'SUN', '1': 'MON', '2': 'TUE', '3': 'WED',
    '4': 'THU', '5': 'FRI', '6': 'SAT', '7': 'SUN'
}

def normalize_cron(expression: str) -> str:
    parts = expression.strip().split()
    if len(parts) != 5:
        return expression
    
    dow_part = parts[4]
    new_dow = ""
    
    # Если там уже буквы - ничего не меняем (грубая проверка)
    # Но лучше пройтись посимвольно
    for char in dow_part:
        if char in DOW_MAP:
            new_dow += DOW_MAP[char]
        else:
            new_dow += char
            
    parts[4] = new_dow
    return " ".join(parts)

async def migrate():
    print("🔄 Исправление дней недели в Cron...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Берем все задачи
        cursor = await db.execute("SELECT id, cron_expression FROM tasks")
        rows = await cursor.fetchall()
        
        count = 0
        for task_id, cron_exp in rows:
            new_cron = normalize_cron(cron_exp)
            
            if new_cron != cron_exp:
                print(f"🔧 ID {task_id}: {cron_exp} -> {new_cron}")
                await db.execute("UPDATE tasks SET cron_expression = ? WHERE id = ?", (new_cron, task_id))
                count += 1
        
        await db.commit()
        print(f"✅ Обновлено задач: {count}")

if __name__ == "__main__":
    asyncio.run(migrate())