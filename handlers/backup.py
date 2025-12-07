import re # Нам понадобятся регулярки
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from database.base import async_session
from database.models import User, Task
from services.cron_manager import add_task, validate_cron
from handlers.common import TaskStates, clear_state_keep_group, get_target_id, get_target_name

router = Router()

# ================= ЭКСПОРТ =================

@router.message(Command("export"))
async def cmd_export(message: types.Message, state: FSMContext):
    target_id = await get_target_id(message, state)
    await clear_state_keep_group(state)
    t_name = "ГРУППЫ" if target_id != message.from_user.id else "твои"
    
    async with async_session() as session:
        query = select(Task).where(Task.user_id == target_id).order_by(Task.id)
        result = await session.execute(query)
        tasks = result.scalars().all()

    if not tasks:
        await message.answer(f"Задач ({t_name}) для экспорта нет.")
        return

    export_lines = []
    for task in tasks:
        # Формируем текст
        # Если есть медиа -> [photo:Age...] Текст
        # Если нет -> Текст
        
        content_prefix = ""
        if task.content_type != "text" and task.file_id:
            content_prefix = f"[{task.content_type}:{task.file_id}] "
        
        # text может быть None, заменим на ""
        safe_text = task.message_text or ""
        
        block = f"{task.cron_expression}\n{content_prefix}{safe_text}"
        export_lines.append(block)
    
    full_text = "\n==========\n".join(export_lines)
    
    if len(full_text) > 4000:
        from aiogram.types import BufferedInputFile
        file = BufferedInputFile(full_text.encode("utf-8"), filename="tasks_backup.txt")
        await message.answer_document(file, caption=f"📂 Бэкап задач ({t_name})")
    else:
        await message.answer(
            f"<code>{full_text}</code>", 
            parse_mode="HTML"
        )

# ================= ИМПОРТ =================

@router.message(Command("import"))
async def cmd_import(message: types.Message, state: FSMContext):
    target_id = await get_target_id(message, state)
    await clear_state_keep_group(state)
    t_name = await get_target_name(state)
    
    await message.answer(
        f"📥 <b>Импорт задач{t_name}</b>\n\n"
        "Пришли список задач. Поддерживаю медиа-теги:\n"
        "<code>[sticker:ID]</code>, <code>[photo:ID]</code> и т.д.",
        parse_mode="HTML"
    )
    await state.set_state(TaskStates.waiting_for_import)

@router.message(TaskStates.waiting_for_import, ~F.text.startswith("/"))
async def process_import(message: types.Message, state: FSMContext):
    text = message.text
    target_id = await get_target_id(message, state)
    
    blocks = text.split("==========")
    success_count = 0
    errors = []
    
    async with async_session() as session:
        res = await session.execute(select(User).where(User.user_id == target_id))
        if not res.scalar_one_or_none():
             session.add(User(user_id=target_id, timezone="Asia/Yekaterinburg"))
             await session.commit()

        res2 = await session.execute(select(User.timezone).where(User.user_id == target_id))
        user_tz = res2.scalar() or "Asia/Yekaterinburg"

        for i, block in enumerate(blocks, 1):
            block = block.strip()
            if not block: continue
            
            lines = block.split("\n", 1)
            if len(lines) < 2:
                errors.append(f"Блок {i}: Нет текста")
                continue
                
            cron_exp = lines[0].strip()
            raw_text = lines[1].strip()
            
            # --- ПАРСИНГ МЕДИА ---
            # Ищем паттерн [type:ID] в начале текста
            # Например: [photo:AgAC...] Доброе утро
            
            c_type = "text"
            f_id = None
            final_text = raw_text
            
            match = re.match(r"^\[(\w+):(.+?)\]\s?(.*)", raw_text, re.DOTALL)
            if match:
                c_type = match.group(1) # photo
                f_id = match.group(2)   # ID
                final_text = match.group(3) # Остаток текста
            
            # Валидация
            is_valid, _ = validate_cron(cron_exp)
            if not is_valid:
                errors.append(f"Блок {i}: Неверный Cron")
                continue
            
            try:
                await add_task(
                    bot=message.bot, session=session, user_id=target_id,
                    cron_exp=cron_exp, text=final_text, timezone_str=user_tz,
                    content_type=c_type, file_id=f_id
                )
                success_count += 1
            except Exception as e:
                errors.append(f"Блок {i}: Ошибка БД {e}")

    report = f"✅ Импортировано: <b>{success_count}</b> задач.\n"
    if errors:
        report += "\n⚠️ <b>Ошибки:</b>\n" + "\n".join(errors)
    
    await message.answer(report, parse_mode="HTML")
    await clear_state_keep_group(state)