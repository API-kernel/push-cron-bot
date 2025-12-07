from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from datetime import datetime
from croniter import croniter
import pytz
import math

from database.base import async_session
from database.models import User, Task
from handlers.common import TaskStates, clear_state_keep_group, get_target_id, humanize_cron, get_real_task_by_number, get_share_text

# Импортируем функции действий (чтобы вызывать их из кнопок)
from services.cron_manager import pause_task, resume_task, delete_task, create_share_snapshot
from handlers.task_actions import start_editing_menu # Для кнопки Edit

router = Router()

ITEMS_PER_PAGE = 10

# --- ХЕЛПЕР: Клавиатура Списка ---
def get_list_keyboard(total_tasks, page=1):
    kb = []
    
    # 1. Кнопки с номерами
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_tasks)
    
    row = []
    for i in range(start_idx + 1, end_idx + 1):
        row.append(types.InlineKeyboardButton(text=str(i), callback_data=f"list_select_{i}"))
        if len(row) == 5: # 5 кнопок в ряд
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    # 2. Пагинация
    total_pages = math.ceil(total_tasks / ITEMS_PER_PAGE)
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"list_page_{page-1}"))
        nav_row.append(types.InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="ignore"))
        if page < total_pages:
            nav_row.append(types.InlineKeyboardButton(text="➡️", callback_data=f"list_page_{page+1}"))
        kb.append(nav_row)
        
    # 3. Управление
    kb.append([types.InlineKeyboardButton(text="⚙️ Управление всеми", callback_data="list_batch_actions")])
    
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- ХЕЛПЕР: Клавиатура Карточки ---
def get_task_keyboard(task_num, is_active):
    pause_btn_text = "⏸ Пауза" if is_active else "▶️ Старт"
    pause_callback = f"task_pause_{task_num}" if is_active else f"task_resume_{task_num}"
    
    kb = [
        [
            types.InlineKeyboardButton(text="✏️ Изменить", callback_data=f"task_edit_{task_num}"),
            types.InlineKeyboardButton(text=pause_btn_text, callback_data=pause_callback)
        ],
        [
            types.InlineKeyboardButton(text="🔗 Поделиться", callback_data=f"task_share_{task_num}"),
            types.InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task_delete_confirm_{task_num}")
        ],
        [types.InlineKeyboardButton(text="🔙 Назад к списку", callback_data="list_back")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


# ================= КОМАНДА /LIST =================

@router.message(Command("list"))
async def cmd_list(message: types.Message, state: FSMContext):
    target_id = await get_target_id(message, state)
    await clear_state_keep_group(state)
    
    # Показываем 1-ю страницу
    await show_list_page(message, target_id, page=1)

# Функция отрисовки страницы (вынесена, чтобы вызывать из колбэка пагинации)
async def show_list_page(message_or_callback, target_id, page):
    is_callback = isinstance(message_or_callback, types.CallbackQuery)
    message = message_or_callback.message if is_callback else message_or_callback
    
    t_name = "ГРУППЫ" if target_id != message.from_user.id else "Твои"
    
    async with async_session() as session:
        # Зона нужна только для расчета времени, в тексте не показываем
        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        user_tz = res.scalar() or "Asia/Yekaterinburg"
        
        query = select(Task).where(Task.user_id == target_id).order_by(Task.id)
        result = await session.execute(query)
        all_tasks = result.scalars().all()

    if not all_tasks:
        text = f"📋 <b>{t_name} задачи:</b>\n\nСписок пуст."
        if is_callback: await message.edit_text(text, parse_mode="HTML")
        else: await message.answer(text, parse_mode="HTML")
        return

    start = (page - 1) * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_tasks = all_tasks[start:end]
    
    # --- ИЗМЕНЕНИЕ ЗАГОЛОВКА ---
    page_info = f" (Стр {page})" if page > 1 else ""
    response = f"📋 <b>{t_name} задачи{page_info}</b>\n\n"
    
    for i, task in enumerate(page_tasks, start + 1):
        if task.is_active:
            status_icon = "" 
            try:
                tz = pytz.timezone(user_tz if "Etc" not in user_tz else "UTC")
                local_now = datetime.now(tz)
                iter = croniter(task.cron_expression, local_now)
                next_run = iter.get_next(datetime).astimezone(tz)
                time_info = f"🔜 {next_run.strftime('%d.%m %H:%M')}"
            except:
                time_info = "🔜 ?"
        else:
            status_icon = "⏸ " 
            time_info = "(На паузе)"

        readable = humanize_cron(task.cron_expression)
        cron_disp = f"⏳ <code>{readable}</code>" if readable == task.cron_expression else f"<b>{readable}</b>"
        
        type_icon = "💬"
        if task.content_type == "photo": type_icon = "🖼 [Фото]"
        elif task.content_type == "video": type_icon = "📹 [Видео]"
        elif task.content_type == "voice": type_icon = "🎤 [Голос]"
        elif task.content_type == "sticker": type_icon = "👻 [Стикер]"
        elif task.content_type == "video_note": type_icon = "⏺ [Кружок]"
        elif task.content_type == "document": type_icon = "📄 [Файл]"

        text_preview = (task.message_text or "")[:30]
        if len(task.message_text or "") > 30: text_preview += "..."

        response += (
            f"{status_icon}<b>№{i}</b> | {time_info}\n"
            f"{cron_disp}\n"
            f"{type_icon} {text_preview}\n\n"
        )
    
    kb = get_list_keyboard(len(all_tasks), page)
    
    if is_callback:
        await message.edit_text(response, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(response, reply_markup=kb, parse_mode="HTML")

# ================= КОЛБЭКИ НАВИГАЦИИ =================

@router.callback_query(F.data.startswith("list_page_"))
async def callback_list_page(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    target_id = await get_target_id(callback, state)
    await show_list_page(callback, target_id, page)
    await callback.answer()

@router.callback_query(F.data == "list_back")
async def callback_list_back(callback: types.CallbackQuery, state: FSMContext):
    target_id = await get_target_id(callback, state)
    await show_list_page(callback, target_id, page=1)
    await callback.answer()

# ================= ПЕРЕХОД В КАРТОЧКУ ЗАДАЧИ =================

@router.callback_query(F.data.startswith("list_select_"))
async def callback_task_select(callback: types.CallbackQuery, state: FSMContext):
    task_num = int(callback.data.split("_")[2])
    target_id = await get_target_id(callback, state)
    
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_num)
        if not task:
            await callback.answer("Задача не найдена (возможно, удалена).", show_alert=True)
            # Обновляем список
            await show_list_page(callback, target_id, 1)
            return
        
        # Формируем Карточку
        status_text = "✅ Активна" if task.is_active else "⏸ На паузе"
        
        text_full = task.message_text or "(нет текста)"
        
        # Красивое расписание
        readable_cron = humanize_cron(task.cron_expression)
        if readable_cron == task.cron_expression:
            # Если не перевелось (сложный крон) - показываем код
            schedule_display = f"⏳ <code>{task.cron_expression}</code>"
        else:
            # Если перевелось - показываем текст жирным
            schedule_display = f"<b>{readable_cron}</b>"
        
        type_map = {
            "text": "💬 Текст",
            "photo": "🖼 Фото",
            "video": "📹 Видео",
            "voice": "🎤 Голосовое",
            "audio": "🎧 Аудио",
            "video_note": "⏺ Кружок",
            "sticker": "👻 Стикер",
            "document": "📄 Файл"
        }

        type_str = type_map.get(task.content_type, task.content_type)
        type_info = f"Тип: {type_str}"

        card_text = (
            f"📌 <b>Задача №{task_num}</b>\n\n"
            f"Статус: {status_text}\n"
            f"Расписание: {schedule_display}\n"
            f"{type_info}\n"
            f"📝 {text_full}"
        )
        
        kb = get_task_keyboard(task_num, task.is_active)
        await callback.message.edit_text(card_text, reply_markup=kb, parse_mode="HTML")
    
    await callback.answer()


# ================= ДЕЙСТВИЯ В КАРТОЧКЕ =================

# --- PAUSE / RESUME ---
@router.callback_query(F.data.startswith("task_pause_") | F.data.startswith("task_resume_"))
async def callback_card_toggle(callback: types.CallbackQuery, state: FSMContext):
    action, task_num = callback.data.split("_")[1], int(callback.data.split("_")[2])
    target_id = await get_target_id(callback, state)
    
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_num)
        if not task: return
        
        if action == "pause":
            await pause_task(session, task.id, target_id)
            await callback.answer("Задача на паузе ⏸")
        else:
            # Нужна зона
            res = await session.execute(select(User.timezone).where(User.user_id == target_id))
            tz = res.scalar() or "Asia/Yekaterinburg"
            await resume_task(callback.message.bot, session, task.id, target_id, tz)
            await callback.answer("Задача запущена ▶️")
            
    # Обновляем карточку (перерисовываем статус и кнопки)
    await callback_task_select(callback, state) 

# --- SHARE ---
@router.callback_query(F.data.startswith("task_share_"))
async def callback_card_share(callback: types.CallbackQuery, state: FSMContext):
    # ... (код получения token) ...
    task_num = int(callback.data.split("_")[2])
    target_id = await get_target_id(callback, state)
    
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_num)
        if not task: return
        token = await create_share_snapshot(session, task.id)
        
        bot_username = (await callback.message.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=share_{token}"
        
        encoded_text = get_share_text(task)
        
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="↗️ Отправить", url=f"https://t.me/share/url?url={link}&text={encoded_text}")]
        ])
        
        # Удаляем карточку, чтобы не мешала
        await callback.message.delete()
        
        await callback.message.answer(
            f"🎁 <b>Поделиться задачей №{task_num}:</b>\n\nНажмите на кнопку ниже, чтобы отправить ссылку на задачу другу.", 
            reply_markup=kb, parse_mode="HTML"
        )
    await callback.answer()

# --- EDIT ---
@router.callback_query(F.data.startswith("task_edit_"))
async def callback_card_edit(callback: types.CallbackQuery, state: FSMContext):
    task_num = int(callback.data.split("_")[2])
    
    # Удаляем карточку перед запуском меню
    await callback.message.delete()
    
    # Теперь вызываем меню (оно отправит новое сообщение)
    # Нам нужно передать message, который мы только что удалили? Нет, объект message остался в памяти.
    # Но start_editing_menu использует message.answer(). Это сработает.
    await start_editing_menu(callback.message, state, task_num)
    await callback.answer()

# --- DELETE ---
@router.callback_query(F.data.startswith("task_delete_confirm_"))
async def callback_card_delete_ask(callback: types.CallbackQuery):
    task_num = callback.data.split("_")[3]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔥 ДА, Удалить", callback_data=f"task_delete_do_{task_num}")],
        [types.InlineKeyboardButton(text="🔙 Нет, назад", callback_data=f"list_select_{task_num}")]
    ])
    await callback.message.edit_text(f"⚠️ <b>Удалить задачу №{task_num}?</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("task_delete_do_"))
async def callback_card_delete_perform(callback: types.CallbackQuery, state: FSMContext):
    task_num = int(callback.data.split("_")[3])
    target_id = await get_target_id(callback, state)
    
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_num)
        if task:
            await delete_task(session, task.id, target_id)
            
    await callback.answer("Удалено 🗑")
    # Возвращаемся в список
    await show_list_page(callback, target_id, 1)

# --- BATCH ACTIONS (Меню "Всех") ---
@router.callback_query(F.data == "list_batch_actions")
async def callback_batch_menu(callback: types.CallbackQuery):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⏸ Пауза ВСЕХ", callback_data="btn_pause_all")],
        [types.InlineKeyboardButton(text="▶️ Старт ВСЕХ", callback_data="btn_resume_all")],
        [types.InlineKeyboardButton(text="🧨 Удалить ВСЁ", callback_data="btn_delete_all")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="list_back")]
    ])
    await callback.message.edit_text("⚙️ <b>Управление всеми задачами:</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()