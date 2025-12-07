from datetime import datetime
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
import pytz
from croniter import croniter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from services.cron_manager import create_share_snapshot

from database.base import async_session
from database.models import User, Task
from services.cron_manager import (
    delete_task, edit_task, pause_task, resume_task, 
    pause_all_tasks, resume_all_tasks, delete_all_tasks, validate_cron
)
# Импортируем общие хелперы
from handlers.common import (
    TaskStates, clear_state_keep_group, get_target_id, 
    get_target_name, get_real_task_by_number, validate_time_format,
    humanize_cron, get_share_text
)

from keyboards import get_presets_keyboard, get_weekdays_keyboard, get_months_keyboard

router = Router()

# ================= ПАУЗА / СТАРТ (PAUSE / RESUME) =================

@router.message(Command("pause"))
async def cmd_pause(message: types.Message, state: FSMContext):
    await clear_state_keep_group(state)
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        await perform_pause(message, state, int(args[1]))
        return
    
    t_name = await get_target_name(state)
    
    # КНОПКА
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏸ Пауза ВСЕХ задач", callback_data="btn_pause_all")]
    ])
    
    await message.answer(f"Введите <b>номер</b> задачи для паузы{t_name}:", parse_mode="HTML", reply_markup=kb)
    await state.set_state(TaskStates.waiting_for_pause_id)

@router.message(TaskStates.waiting_for_pause_id, ~F.text.startswith("/"))
async def process_pause_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await perform_pause(message, state, int(message.text))
    await clear_state_keep_group(state)

async def perform_pause(message: types.Message, state: FSMContext, task_number: int):
    target_id = await get_target_id(message, state)
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_number)
        if not task:
            await message.answer(f"❌ Задача №{task_number} не найдена.")
            return
        await pause_task(session, task.id, target_id)
    await message.answer(f"⏸ Задача №<b>{task_number}</b> на паузе.", parse_mode="HTML")

# --- RESUME ---
@router.message(Command("resume"))
async def cmd_resume(message: types.Message, state: FSMContext):
    await clear_state_keep_group(state)
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        await perform_resume(message, state, int(args[1]))
        return
    t_name = await get_target_name(state)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Запустить ВСЕ задачи", callback_data="btn_resume_all")]
    ])
    
    await message.answer(f"Введите <b>номер</b> задачи для запуска{t_name}:", parse_mode="HTML", reply_markup=kb)
    await state.set_state(TaskStates.waiting_for_resume_id)

@router.message(TaskStates.waiting_for_resume_id, ~F.text.startswith("/"))
async def process_resume_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await perform_resume(message, state, int(message.text))
    await clear_state_keep_group(state)

async def perform_resume(message: types.Message, state: FSMContext, task_number: int):
    target_id = await get_target_id(message, state)
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_number)
        if not task:
            await message.answer(f"❌ Задача №{task_number} не найдена.")
            return
        # Получаем таймзону ЦЕЛИ
        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        tz = res.scalar() or "Asia/Yekaterinburg"
        await resume_task(message.bot, session, task.id, target_id, tz)
    await message.answer(f"✅ Задача №<b>{task_number}</b> запущена!", parse_mode="HTML")

# ================= УДАЛЕНИЕ (DELETE) =================

@router.message(Command("delete"))
async def cmd_delete(message: types.Message, state: FSMContext):
    await clear_state_keep_group(state)
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        await perform_delete(message, state, int(args[1]))
        return
    t_name = await get_target_name(state)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧨 Удалить ВСЕ задачи", callback_data="btn_delete_all")]
    ])
    
    await message.answer(f"Введите <b>номер</b> задачи для удаления{t_name}:", parse_mode="HTML", reply_markup=kb)
    await state.set_state(TaskStates.waiting_for_delete_id)

@router.message(TaskStates.waiting_for_delete_id, ~F.text.startswith("/"))
async def process_delete_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await perform_delete(message, state, int(message.text))
    await clear_state_keep_group(state)

async def perform_delete(message: types.Message, state: FSMContext, task_number: int):
    target_id = await get_target_id(message, state)
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_number)
        if not task:
            await message.answer(f"❌ Задача №{task_number} не найдена.")
            return
        success = await delete_task(session, task.id, target_id)
    if success: await message.answer(f"✅ Задача №<b>{task_number}</b> удалена.", parse_mode="HTML")
    else: await message.answer("❌ Ошибка при удалении.")

# ================= РЕДАКТИРОВАНИЕ (EDIT) =================
# ================= НОВОЕ РЕДАКТИРОВАНИЕ =================

# 1. Вход в команду
@router.message(Command("edit"))
async def cmd_edit(message: types.Message, state: FSMContext):
    await clear_state_keep_group(state)
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        await start_editing_menu(message, state, int(args[1]))
        return
    t_name = await get_target_name(state)
    await message.answer(f"Введите <b>номер</b> задачи для редактирования{t_name}:", parse_mode="HTML")
    await state.set_state(TaskStates.waiting_for_edit_id)

@router.message(TaskStates.waiting_for_edit_id, ~F.text.startswith("/"))
async def process_edit_id_input(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await start_editing_menu(message, state, int(message.text))

async def start_editing_menu(message: types.Message, state: FSMContext, task_number: int):
    target_id = await get_target_id(message, state)
    
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_number)
        if not task:
            await message.answer(f"❌ Задача №{task_number} не найдена.")
            await clear_state_keep_group(state)
            return
        
        await state.update_data(
            editing_task_id=task.id, 
            editing_task_number=task_number,
            old_cron=task.cron_expression,
            old_text=task.message_text
        )
        
        type_icon = "📄"
        if task.content_type == "photo": type_icon = "🖼"
        elif task.content_type == "sticker": type_icon = "👻"
        
        # --- КРАСИВЫЙ ВЫВОД КРОНА ---
        readable_cron = humanize_cron(task.cron_expression)
        if readable_cron == task.cron_expression:
            # Если не перевелось - показываем код
            cron_display = f"<code>{task.cron_expression}</code>"
        else:
            # Если перевелось - жирный текст
            cron_display = f"<b>{readable_cron}</b>"
        
        info_text = (
            f"✏️ <b>Редактирование №{task_number}</b>\n\n"
            f"🕒 Расписание: {cron_display}\n"
            f"{type_icon} Текст: {task.message_text or '(пусто)'}\n\n"
            "<b>Что будем менять?</b>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏰ Расписание (Время)", callback_data="edit_action_time")],
            [InlineKeyboardButton(text="📝 Текст / Подпись", callback_data="edit_action_text")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="edit_action_cancel")]
        ])
        
        await message.answer(info_text, reply_markup=kb, parse_mode="HTML")
        await state.set_state(TaskStates.editing_select_action)

# 3. Обработка выбора (Роутер действий)
@router.callback_query(TaskStates.editing_select_action)
async def process_edit_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    
    if action == "edit_action_cancel":
        await callback.message.edit_text("❌ Редактирование отменено.")
        await clear_state_keep_group(state)
        return

    elif action == "edit_action_text":
        data = await state.get_data()
        current_text = data.get('old_text', '')
        
        await callback.message.edit_text(
            f"Текущий текст:\n<code>{current_text}</code>\n\n"
            "Ваш новый вариант:",
            parse_mode="HTML"
        )
        await state.set_state(TaskStates.editing_text_input)
        
    elif action == "edit_action_time":
        await callback.message.edit_text("📅 Выберите новый тип расписания:", reply_markup=get_presets_keyboard())
        await state.set_state(TaskStates.editing_preset_choice)
    
    await callback.answer()

# --- ВЕТКА: ИЗМЕНЕНИЕ ТЕКСТА ---
@router.message(TaskStates.editing_text_input, ~F.text.startswith("/"))
async def process_new_text(message: types.Message, state: FSMContext):
    new_text = message.text
    data = await state.get_data()
    # Оставляем старый крон
    final_cron = data['old_cron']
    
    await finalize_edit(message, state, final_cron, new_text)


# --- ВЕТКА: ИЗМЕНЕНИЕ ВРЕМЕНИ (Пресеты) ---
# (Тут почти копия логики из adding.py, но состояния другие)

@router.callback_query(TaskStates.editing_preset_choice)
async def process_edit_preset(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    await state.update_data(preset_type=action)

    if action == "preset_custom":
        await callback.message.edit_text("Введите Cron (например, <code>*/5 * * * *</code>):", parse_mode="HTML")
        await state.set_state(TaskStates.editing_cron_input)
    elif action == "preset_daily":
        await callback.message.edit_text("Время <b>ЧЧ:ММ</b>:", parse_mode="HTML")
        await state.set_state(TaskStates.editing_time_input)
    elif action == "preset_weekly":
        await state.update_data(selected_weekdays=[])
        await callback.message.edit_text("Выберите дни недели:", reply_markup=get_weekdays_keyboard([]))
        await state.set_state(TaskStates.editing_weekday)
    elif action == "preset_monthly":
        await callback.message.edit_text("День месяца (1-31) или 'L' для последнего дня:")
        await state.set_state(TaskStates.editing_day_month)
    elif action == "preset_yearly":
        await callback.message.edit_text("Выберите месяц:", reply_markup=get_months_keyboard())
        await state.set_state(TaskStates.editing_month)
    await callback.answer()

# Логика дней (копия)
@router.callback_query(TaskStates.editing_weekday, F.data.startswith("weekday_"))
async def process_edit_weekday(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "weekday_done":
        user_data = await state.get_data()
        if not user_data.get("selected_weekdays"):
            await callback.answer("Выберите день!", show_alert=True)
            return
        await callback.message.edit_text(f"Дни выбраны. Введите время (ЧЧ:ММ):")
        await state.set_state(TaskStates.editing_time_input)
        await callback.answer()
        return
    day = data.split("_")[1]
    user_data = await state.get_data()
    selected = user_data.get("selected_weekdays", [])
    if day in selected: selected.remove(day)
    else: selected.append(day)
    await state.update_data(selected_weekdays=selected)
    try: await callback.message.edit_reply_markup(reply_markup=get_weekdays_keyboard(selected))
    except: pass
    await callback.answer()

# Логика месяцев (копия)
@router.callback_query(TaskStates.editing_month)
async def process_edit_month(callback: types.CallbackQuery, state: FSMContext):
    month = callback.data.split("_")[1]
    await state.update_data(month=month)
    await callback.message.edit_text(f"Месяц выбран. Введите день месяца (1-31):")
    await state.set_state(TaskStates.editing_day_month)
    await callback.answer()

# Логика ввода чисел (копия)
@router.message(TaskStates.editing_day_month, ~F.text.startswith("/"))
async def process_edit_day_month(message: types.Message, state: FSMContext):
    day_str = message.text.strip().upper()
    if day_str == 'L':
        await state.update_data(day_month='L')
        await message.answer("Введите время (ЧЧ:ММ):")
        await state.set_state(TaskStates.editing_time_input)
        return

    if not day_str.isdigit():
        await message.answer("❌ Введите число от 1 до 31 или букву 'L'.")
        return
        
    day = int(day_str)
    if not (1 <= day <= 31):
        await message.answer("❌ Число должно быть от 1 до 31.")
        return

    await state.update_data(day_month=str(day))
    await message.answer("Введите время (ЧЧ:ММ):")
    await state.set_state(TaskStates.editing_time_input)

# Логика времени и генерации Крона (копия)
@router.message(TaskStates.editing_time_input, ~F.text.startswith("/"))
async def process_edit_time(message: types.Message, state: FSMContext):
    time_str = message.text.strip()
    
    # Используем функцию из common.py
    if not validate_time_format(time_str):
        await message.answer("❌ Неверный формат. Используйте ЧЧ:ММ (например 09:00).")
        return

    hours, minutes = map(int, time_str.split(":"))
    data = await state.get_data()
    preset = data['preset_type']
    cron_res = ""
    
    if preset == "preset_daily":
        cron_res = f"{minutes} {hours} * * *"
        
    elif preset == "preset_weekly":
        weekdays = ",".join(data.get('selected_weekdays', []))
        cron_res = f"{minutes} {hours} * * {weekdays}"
        
    elif preset == "preset_monthly":
        cron_res = f"{minutes} {hours} {data['day_month']} * *"
        
    elif preset == "preset_yearly":
        cron_res = f"{minutes} {hours} {data['day_month']} {data['month']} *"
    
    # Сохраняем! Текст оставляем старый (берем из сохраненного при старте edit)
    old_text = data.get('old_text', "")
    
    await finalize_edit(message, state, cron_res, old_text)

# Логика ручного крона
@router.message(TaskStates.editing_cron_input, ~F.text.startswith("/"))
async def process_edit_manual_cron(message: types.Message, state: FSMContext):
    new_cron = message.text.strip()
    is_valid, err = validate_cron(new_cron)
    if not is_valid:
        await message.answer(f"Ошибка: {err}")
        return
    
    data = await state.get_data()
    old_text = data['old_text']
    await finalize_edit(message, state, new_cron, old_text)


# --- ФИНАЛИЗАЦИЯ (Сохранение в БД) ---
async def finalize_edit(message: types.Message, state: FSMContext, new_cron: str, new_text: str):
    data = await state.get_data()
    task_id = data['editing_task_id']
    task_num = data['editing_task_number']
    
    target_id = await get_target_id(message, state)
    
    async with async_session() as session:
        # Нужна таймзона для перезапуска планировщика
        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        user_tz = res.scalar() or "Asia/Yekaterinburg"
        
        try:
            await edit_task(
                bot=message.bot, 
                session=session, 
                task_id=task_id, 
                user_id=target_id, 
                cron_exp=new_cron, 
                text=new_text, 
                timezone_str=user_tz
            )
            await message.answer(f"✅ Задача №<b>{task_num}</b> успешно обновлена!", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка обновления: {e}")
            
    await clear_state_keep_group(state)


# --- ОБНОВЛЕННЫЙ START_EDITING ---
async def start_editing(message: types.Message, state: FSMContext, task_number: int):
    target_id = await get_target_id(message, state)
    async with async_session() as session:
        task = await get_real_task_by_number(session, target_id, task_number)
        if not task:
            await message.answer(f"❌ Задача №{task_number} не найдена.")
            await clear_state_keep_group(state)
            return
        
        # Предупреждение о медиа
        media_warning = ""
        if task.content_type != "text":
            media_warning = "\n⚠️ <b>Внимание:</b> Эта задача содержит Медиа-файл. Вы можете изменить только его <b>Текст/Подпись</b>. Сам файл останется прежним."

        await state.update_data(editing_task_id=task.id, editing_task_number=task_number, old_cron=task.cron_expression, old_text=task.message_text or "")
    
    await message.answer(
        f"Редактирование задачи №<b>{task_number}</b>.{media_warning}\n\n"
        f"Текущий Cron: <code>{task.cron_expression}</code>\n"
        "Введите новый или отправьте <code>.</code> чтобы оставить:", 
        parse_mode="HTML"
    )
    await state.set_state(TaskStates.editing_cron)


@router.message(TaskStates.editing_cron, ~F.text.startswith("/"))
async def process_edit_cron(message: types.Message, state: FSMContext):
    input_text = message.text.strip()
    if input_text == ".":
        data = await state.get_data()
        final_cron = data['old_cron']
        await message.answer("✅ Cron оставлен без изменений.")
    else:
        is_valid, error_msg = validate_cron(input_text)
        if not is_valid:
            await message.answer(f"❌ Ошибка: {error_msg}")
            return
        final_cron = input_text
    await state.update_data(final_cron=final_cron)
    data = await state.get_data()
    await message.answer(f"Текущий текст: {data['old_text']}\nВведите новый или отправьте <code>.</code>:", parse_mode="HTML")
    await state.set_state(TaskStates.editing_text)

@router.message(TaskStates.editing_text, ~F.text.startswith("/"))
async def process_edit_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    input_text = message.text.strip()
    final_text = data['old_text'] if input_text == "." else message.text
    
    task_id = data['editing_task_id']
    task_num = data.get('editing_task_number', '?')
    
    # Важно: берем target_id (группа или юзер)
    target_id = await get_target_id(message, state)

    async with async_session() as session:
        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        user_tz = res.scalar() or "Asia/Yekaterinburg"
        try:
            await edit_task(bot=message.bot, session=session, task_id=task_id, user_id=target_id, 
                            cron_exp=data['final_cron'], text=final_text, timezone_str=user_tz)
            await message.answer(f"✅ Задача №<b>{task_num}</b> обновлена!", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка обновления: {e}")
    
    await clear_state_keep_group(state)

# ================= ШАРИНГ (SHARE) =================

@router.message(Command("share"))
async def cmd_share(message: types.Message, state: FSMContext):
    await clear_state_keep_group(state)
    args = message.text.split()
    
    # Если аргумент есть (/share 1)
    if len(args) > 1 and args[1].isdigit():
        await perform_share(message, state, int(args[1]))
        return
        
    t_name = await get_target_name(state)
    await message.answer(f"Введите <b>номер</b> задачи, которой хотите поделиться{t_name}:", parse_mode="HTML")
    await state.set_state(TaskStates.waiting_for_share_id) # <-- Добавь это состояние в common.py!

@router.message(TaskStates.waiting_for_share_id, ~F.text.startswith("/"))
async def process_share_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await perform_share(message, state, int(message.text))
    await clear_state_keep_group(state)

async def perform_share(message: types.Message, state: FSMContext, task_number: int):
    target_id = await get_target_id(message, state)
    
    async with async_session() as session:
        # Ищем задачу, чтобы проверить, что она существует и принадлежит юзеру
        task = await get_real_task_by_number(session, target_id, task_number)
        if not task:
            await message.answer(f"❌ Задача №{task_number} не найдена.")
            return
        
        # СОЗДАЕМ СНЕПШОТ (Независимая ссылка)
        token = await create_share_snapshot(session, task.id)
            
        bot_username = (await message.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=share_{token}"
        
        encoded_text = get_share_text(task)
        
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="↗️ Отправить другу", url=f"https://t.me/share/url?url={link}&text={encoded_text}")]
        ])
        
        await message.answer(
            f"🎁 <b>Ссылка на задачу №{task_number}:</b>\n\n"
            f"{link}\n\n"
            "Эта ссылка — <b>снимок</b> задачи. Если вы измените или удалите оригинал, ссылка всё равно будет работать.", 
            parse_mode="HTML",
            reply_markup=kb
        )

# --- ОБРАБОТКА КНОПОК "ВСЕХ" ---

@router.callback_query(F.data == "btn_pause_all")
async def callback_pause_all(callback: types.CallbackQuery, state: FSMContext):
    # 1. Определяем правильный ID
    data = await state.get_data()
    group_id = data.get("active_group_id")
    target_id = group_id if group_id else callback.from_user.id # <-- БЕРЕМ ID ЮЗЕРА, А НЕ БОТА
    
    async with async_session() as session:
        await pause_all_tasks(session, target_id)
    
    await callback.message.edit_text("⏸ <b>Все задачи поставлены на паузу.</b>", parse_mode="HTML")
    await clear_state_keep_group(state)

@router.callback_query(F.data == "btn_resume_all")
async def callback_resume_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    group_id = data.get("active_group_id")
    target_id = group_id if group_id else callback.from_user.id
    
    async with async_session() as session:
        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        tz = res.scalar() or "Asia/Yekaterinburg"
        await resume_all_tasks(callback.message.bot, session, target_id, tz)
    
    await callback.message.edit_text("✅ <b>Все задачи запущены!</b>", parse_mode="HTML")
    await clear_state_keep_group(state)

@router.callback_query(F.data == "confirm_delete_all")
async def callback_confirm_delete_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    group_id = data.get("active_group_id")
    target_id = group_id if group_id else callback.from_user.id
    
    async with async_session() as session:
        await delete_all_tasks(session, target_id)
    await callback.message.edit_text("🗑 <b>Все задачи удалены.</b>", parse_mode="HTML")
    await clear_state_keep_group(state)

@router.callback_query(F.data == "confirm_delete_all")
async def callback_confirm_delete_all(callback: types.CallbackQuery, state: FSMContext):
    target_id = await get_target_id(callback, state)
    async with async_session() as session:
        await delete_all_tasks(session, target_id)
    await callback.message.edit_text("🗑 <b>Все задачи удалены.</b>", parse_mode="HTML")
    await clear_state_keep_group(state)

@router.callback_query(F.data == "cancel_delete_all")
async def callback_cancel_delete_all(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✅ Удаление отменено.")
    await clear_state_keep_group(state)