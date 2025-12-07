from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Task, User, SharedLink
from database.base import async_session
from croniter import croniter
from datetime import datetime
import uuid

scheduler = AsyncIOScheduler()

# Карта перевода Linux (0-7) -> English Names
# Linux: 0=Sun, 1=Mon ... 7=Sun
DOW_MAP = {
    '0': 'SUN', '1': 'MON', '2': 'TUE', '3': 'WED',
    '4': 'THU', '5': 'FRI', '6': 'SAT', '7': 'SUN'
}

def normalize_cron(expression: str) -> str:
    """
    Заменяет цифры дней недели на имена (MON, TUE...), 
    чтобы избежать путаницы между Linux (0=Sun) и Python (0=Mon).
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        return expression # Если формат кривой, вернем как есть, валидатор потом отловит
    
    dow_part = parts[4]
    new_dow = ""
    
    # Проходим по символам 5-й части
    # Т.к. дни недели это только цифры 0-7, знаки -,/,* и запятая,
    # мы можем просто заменять цифры на буквы.
    for char in dow_part:
        if char in DOW_MAP:
            new_dow += DOW_MAP[char]
        else:
            new_dow += char
            
    parts[4] = new_dow
    return " ".join(parts)

async def send_message_job(bot, chat_id: int, text: str, content_type: str = "text", file_id: str = None):
    try:
        if content_type == "text":
            await bot.send_message(chat_id=chat_id, text=text)
            return

        if content_type == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=text)
        elif content_type == "video":
            await bot.send_video(chat_id=chat_id, video=file_id, caption=text)
        elif content_type == "audio":
            await bot.send_audio(chat_id=chat_id, audio=file_id, caption=text)
        elif content_type == "document":
            await bot.send_document(chat_id=chat_id, document=file_id, caption=text)
        
        elif content_type == "voice":
            await bot.send_voice(chat_id=chat_id, voice=file_id)
            if text: await bot.send_message(chat_id=chat_id, text=text)
        elif content_type == "video_note":
            await bot.send_video_note(chat_id=chat_id, video_note=file_id)
            if text: await bot.send_message(chat_id=chat_id, text=text)
        elif content_type == "sticker":
            await bot.send_sticker(chat_id=chat_id, sticker=file_id)
            if text: await bot.send_message(chat_id=chat_id, text=text)
        else:
            await bot.send_message(chat_id=chat_id, text=f"[{content_type}] {text}")

    except Exception as e:
        print(f"[ERROR] {chat_id}: {e}")

def validate_cron(expression: str):
    # Сначала нормализуем (превращаем 1 в MON), потом проверяем
    norm_exp = normalize_cron(expression)
    parts = norm_exp.strip().split()
    
    if len(parts) != 5: return False, "Должно быть ровно 5 полей."
    try:
        croniter(norm_exp, datetime.now())
        return True, ""
    except Exception as e:
        return False, str(e)

async def add_task(bot, session: AsyncSession, user_id: int, cron_exp: str, text: str, timezone_str: str, 
                   content_type: str = "text", file_id: str = None):
    
    # НОРМАЛИЗАЦИЯ ПЕРЕД СОХРАНЕНИЕМ
    final_cron = normalize_cron(cron_exp)
    
    token = str(uuid.uuid4())[:8]
    new_task = Task(
        user_id=user_id,
        cron_expression=final_cron, # Сохраняем уже MON, TUE...
        message_text=text,
        content_type=content_type,
        file_id=file_id,
        share_link_token=token,
        is_active=True
    )
    session.add(new_task)
    await session.commit()
    await session.refresh(new_task) 

    scheduler.add_job(
        send_message_job,
        trigger=CronTrigger.from_crontab(final_cron, timezone=timezone_str),
        id=str(new_task.id),
        kwargs={
            "bot": bot, "chat_id": user_id, 
            "text": text, "content_type": content_type, "file_id": file_id
        },
        replace_existing=True
    )
    return new_task.id

async def edit_task(bot, session: AsyncSession, task_id: int, user_id: int, cron_exp: str, text: str, timezone_str: str):
    
    # НОРМАЛИЗАЦИЯ
    final_cron = normalize_cron(cron_exp)
    
    stmt = update(Task).where(Task.id == task_id, Task.user_id == user_id).values(
        cron_expression=final_cron,
        message_text=text
    )
    await session.execute(stmt)
    await session.commit()
    
    res = await session.execute(select(Task).where(Task.id == task_id))
    task = res.scalar_one()

    scheduler.add_job(
        send_message_job,
        trigger=CronTrigger.from_crontab(final_cron, timezone=timezone_str),
        id=str(task_id),
        kwargs={
            "bot": bot, "chat_id": user_id, 
            "text": text, "content_type": task.content_type, "file_id": task.file_id
        },
        replace_existing=True
    )

async def delete_task(session: AsyncSession, task_id: int, user_id: int) -> bool:
    query = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    result = await session.execute(query)
    task = result.scalar_one_or_none()
    if not task: return False
    await session.delete(task)
    await session.commit()
    try: scheduler.remove_job(str(task_id))
    except: pass
    return True

async def pause_task(session: AsyncSession, task_id: int, user_id: int) -> bool:
    stmt = update(Task).where(Task.id == task_id, Task.user_id == user_id).values(is_active=False)
    result = await session.execute(stmt)
    await session.commit()
    try: scheduler.remove_job(str(task_id))
    except: pass 
    return result.rowcount > 0

async def resume_task(bot, session: AsyncSession, task_id: int, user_id: int, timezone_str: str) -> bool:
    query = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    result = await session.execute(query)
    task = result.scalar_one_or_none()
    if not task: return False
    task.is_active = True
    await session.commit()
    scheduler.add_job(
        send_message_job,
        trigger=CronTrigger.from_crontab(task.cron_expression, timezone=timezone_str),
        id=str(task.id),
        kwargs={
            "bot": bot, "chat_id": user_id, 
            "text": task.message_text, 
            "content_type": task.content_type, 
            "file_id": task.file_id
        },
        replace_existing=True
    )
    return True

async def pause_all_tasks(session: AsyncSession, user_id: int):
    result = await session.execute(select(Task.id).where(Task.user_id == user_id))
    task_ids = result.scalars().all()
    stmt = update(Task).where(Task.user_id == user_id).values(is_active=False)
    await session.execute(stmt)
    await session.commit()
    for t_id in task_ids:
        try: scheduler.remove_job(str(t_id))
        except: pass

async def resume_all_tasks(bot, session: AsyncSession, user_id: int, timezone_str: str):
    result = await session.execute(select(Task).where(Task.user_id == user_id))
    tasks = result.scalars().all()
    stmt = update(Task).where(Task.user_id == user_id).values(is_active=True)
    await session.execute(stmt)
    await session.commit()
    for task in tasks:
        try:
            scheduler.add_job(
                send_message_job,
                trigger=CronTrigger.from_crontab(task.cron_expression, timezone=timezone_str),
                id=str(task.id),
                kwargs={
                    "bot": bot, "chat_id": user_id, 
                    "text": task.message_text,
                    "content_type": task.content_type, 
                    "file_id": task.file_id
                },
                replace_existing=True
            )
        except Exception as e:
            print(f"Error resuming task {task.id}: {e}")

async def delete_all_tasks(session: AsyncSession, user_id: int):
    result = await session.execute(select(Task.id).where(Task.user_id == user_id))
    task_ids = result.scalars().all()
    stmt = delete(Task).where(Task.user_id == user_id)
    await session.execute(stmt)
    await session.commit()
    for t_id in task_ids:
        try: scheduler.remove_job(str(t_id))
        except: pass

async def restore_tasks(bot):
    print("🔄 Восстановление задач...")
    async with async_session() as session:
        query = select(Task, User).join(User, Task.user_id == User.user_id).where(Task.is_active == True)
        result = await session.execute(query)
        count = 0
        for task, user in result:
            try:
                scheduler.add_job(
                    send_message_job,
                    trigger=CronTrigger.from_crontab(task.cron_expression, timezone=user.timezone),
                    id=str(task.id),
                    kwargs={
                        "bot": bot, "chat_id": task.user_id, 
                        "text": task.message_text,
                        "content_type": task.content_type, 
                        "file_id": task.file_id
                    },
                    replace_existing=True
                )
                count += 1
            except Exception as e:
                print(f"⚠️ Ошибка восстановления задачи {task.id}: {e}")
        print(f"✅ Восстановлено: {count}")
        
# --- ЛОГИКА СНЕПШОТОВ (SHARING) ---

async def create_share_snapshot(session: AsyncSession, task_id: int):
    """Берет задачу, создает её копию в shared_links и возвращает токен"""
    # 1. Получаем задачу
    res = await session.execute(select(Task).where(Task.id == task_id))
    task = res.scalar_one_or_none()
    if not task: return None
    
    # 2. Генерируем токен
    token = str(uuid.uuid4())[:8]
    
    # 3. Создаем снепшот
    snapshot = SharedLink(
        token=token,
        cron_expression=task.cron_expression,
        message_text=task.message_text,
        content_type=task.content_type,
        file_id=task.file_id
    )
    session.add(snapshot)
    await session.commit()
    
    return token

async def get_shared_snapshot(session: AsyncSession, token: str):
    """Ищет запись в таблице shared_links"""
    res = await session.execute(select(SharedLink).where(SharedLink.token == token))
    return res.scalar_one_or_none()