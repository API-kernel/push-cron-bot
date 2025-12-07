from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from database.base import async_session
from database.models import User
from services.cron_manager import add_task, validate_cron
from keyboards import get_presets_keyboard, get_weekdays_keyboard, get_months_keyboard
from handlers.common import TaskStates, clear_state_keep_group, get_target_id, validate_time_format, humanize_cron 

router = Router()


# ================= ЛОГИКА ДОБАВЛЕНИЯ (/add) =================

@router.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    group_id = await clear_state_keep_group(state)
    if message.chat.type == "private":
        target_text = " для <b>ГРУППЫ</b>" if group_id else ""
        await message.answer(f"📅 Как будем настраивать расписание{target_text}?", reply_markup=get_presets_keyboard(), parse_mode="HTML")
        await state.set_state(TaskStates.waiting_for_preset)
        return
    chat_id = message.chat.id
    bot_username = (await message.bot.get_me()).username
    safe_chat_id = str(chat_id).replace("-", "m")
    url = f"https://t.me/{bot_username}?start=addgroup_{safe_chat_id}"
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Настроить в ЛС", url=url)]])
    await message.answer("Настрой задачу у меня в личке:", reply_markup=kb)

@router.message(F.text == "➕ Добавить в группу")
async def menu_add_group(message: types.Message, state: FSMContext):
    await cmd_add(message, state)

@router.callback_query(TaskStates.waiting_for_preset)
async def process_preset_choice(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    await state.update_data(preset_type=action)
    if action == "preset_custom":
        await callback.message.edit_text("Введите Cron (например, <code>*/5 * * * *</code>):", parse_mode="HTML")
        await state.set_state(TaskStates.adding_cron)
    elif action == "preset_daily":
        await callback.message.edit_text("Время <b>ЧЧ:ММ</b> (например 08:30):", parse_mode="HTML")
        await state.set_state(TaskStates.waiting_for_time)
    elif action == "preset_weekly":
        await state.update_data(selected_weekdays=[])
        await callback.message.edit_text("Выберите дни недели:", reply_markup=get_weekdays_keyboard([]))
        await state.set_state(TaskStates.waiting_for_weekday)
    elif action == "preset_monthly":
        await callback.message.edit_text("Введите день месяца (1-31) или 'L' для последнего дня:")
        await state.set_state(TaskStates.waiting_for_day_month)
    elif action == "preset_yearly":
        await state.update_data(selected_months=[])
        await callback.message.edit_text("Выберите месяцы:", reply_markup=get_months_keyboard([]))
        await state.set_state(TaskStates.waiting_for_month)
    await callback.answer()

@router.callback_query(TaskStates.waiting_for_weekday, F.data.startswith("weekday_"))
async def process_weekday(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "weekday_done":
        user_data = await state.get_data()
        selected = user_data.get("selected_weekdays", [])
        if not selected:
            await callback.answer("❌ Выберите хотя бы один день!", show_alert=True)
            return
        await callback.message.edit_text(f"Дни выбраны. Введите время (ЧЧ:ММ):")
        await state.set_state(TaskStates.waiting_for_time)
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

@router.callback_query(TaskStates.waiting_for_month, F.data.startswith("month_"))
async def process_month(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "month_done":
        user_data = await state.get_data()
        selected = user_data.get("selected_months", [])
        if not selected:
            await callback.answer("❌ Выберите хотя бы один месяц!", show_alert=True)
            return
        await callback.message.edit_text(f"Месяцы выбраны. Введите день месяца (1-31):")
        await state.set_state(TaskStates.waiting_for_day_month)
        await callback.answer()
        return
    
    month = data.split("_")[1]
    user_data = await state.get_data()
    selected = user_data.get("selected_months", [])
    if month in selected:
        selected.remove(month)
    else:
        selected.append(month)
    
    await state.update_data(selected_months=selected)
    
    try:
        await callback.message.edit_reply_markup(reply_markup=get_months_keyboard(selected))
    except Exception as e:
        print(f"Error updating months keyboard: {e}") # Для отладки
    
    await callback.answer()

@router.message(TaskStates.waiting_for_day_month, ~F.text.startswith("/"))
async def process_day_month(message: types.Message, state: FSMContext):
    day_str = message.text.strip().upper()
    if day_str == 'L':
        await state.update_data(day_month='L')
        await message.answer("Введите время (ЧЧ:ММ):")
        await state.set_state(TaskStates.waiting_for_time)
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
    await state.set_state(TaskStates.waiting_for_time)

@router.message(TaskStates.waiting_for_time, ~F.text.startswith("/"))
async def process_time_input(message: types.Message, state: FSMContext):
    time_str = message.text.strip()
    if not validate_time_format(time_str):
        await message.answer("❌ Неверный формат. ЧЧ:ММ")
        return
    hours, minutes = map(int, time_str.split(":"))
    data = await state.get_data()
    preset = data['preset_type']
    cron_res = ""
    if preset == "preset_daily": cron_res = f"{minutes} {hours} * * *"
    elif preset == "preset_weekly":
        weekdays_str = ",".join(data.get('selected_weekdays', []))
        cron_res = f"{minutes} {hours} * * {weekdays_str}"
    elif preset == "preset_monthly": cron_res = f"{minutes} {hours} {data['day_month']} * *"
    elif preset == "preset_yearly":
        months_str = ",".join(data.get('selected_months', []))
        cron_res = f"{minutes} {hours} {data['day_month']} {months_str} *"
    await state.update_data(cron_exp=cron_res)
    
    # Красивый вывод
    readable_cron = humanize_cron(cron_res)
    cron_display = f"<code>{cron_res}</code>" if readable_cron == cron_res else f"<b>{readable_cron}</b>"
    
    await message.answer(f"✅ Расписание: {cron_display}\n\nТеперь отправьте <b>Текст</b>, <b>Фото</b>, <b>Стикер</b> или <b>Голосовое</b>.", parse_mode="HTML")
    await state.set_state(TaskStates.adding_text)

@router.message(TaskStates.adding_cron, ~F.text.startswith("/"))
async def process_custom_cron(message: types.Message, state: FSMContext):
    cron_exp = message.text.strip()
    is_valid, error_msg = validate_cron(cron_exp)
    if not is_valid:
        await message.answer(f"❌ Ошибка: {error_msg}")
        return
    await state.update_data(cron_exp=cron_exp)
    await message.answer("Теперь отправьте <b>Текст</b>, <b>Фото</b>, <b>Стикер</b> или <b>Голосовое</b>.", parse_mode="HTML")
    await state.set_state(TaskStates.adding_text)

# ================= ОБРАБОТКА МЕДИА =================

@router.message(TaskStates.adding_text, ~F.text.startswith("/"))
async def process_add_content(message: types.Message, state: FSMContext):
    content_type = "text"
    file_id = None
    text_content = message.text or message.caption or ""
    
    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
    elif message.sticker:
        content_type = "sticker"
        file_id = message.sticker.file_id
    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id
    elif message.audio:
        content_type = "audio"
        file_id = message.audio.file_id
    elif message.video_note:
        content_type = "video_note"
        file_id = message.video_note.file_id
    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
    
    await state.update_data(content_type=content_type, file_id=file_id, final_text=text_content)
    
    if content_type != "text" and not text_content:
        # КЛАВИАТУРА "БЕЗ ТЕКСТА"
        kb = types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="➡️ Оставить без текста")]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer("Файл принят! 💾\nНапишите описание к файлу или нажмите кнопку:", reply_markup=kb)
        await state.set_state(TaskStates.waiting_for_media_note)
        return

    await finalize_task(message, state)

@router.message(TaskStates.waiting_for_media_note, ~F.text.startswith("/"))
async def process_media_note(message: types.Message, state: FSMContext):
    text = message.text
    if text == "➡️ Оставить без текста" or text == "/skip":
        text = ""
    await state.update_data(final_text=text)
    await finalize_task(message, state)

async def finalize_task(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cron_exp = data['cron_exp']
    msg_text = data.get('final_text', "")
    c_type = data.get('content_type', "text")
    f_id = data.get('file_id')
    
    target_id = await get_target_id(message, state)
    
    async with async_session() as session:
        res = await session.execute(select(User).where(User.user_id == target_id))
        if not res.scalar_one_or_none():
            session.add(User(user_id=target_id, timezone="Asia/Yekaterinburg"))
            await session.commit()

        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        user_tz = res.scalar() or "Asia/Yekaterinburg"

        try:
            await add_task(bot=message.bot, session=session, user_id=target_id, 
                           cron_exp=cron_exp, text=msg_text, timezone_str=user_tz,
                           content_type=c_type, file_id=f_id)
            
            t_name = "в <b>ГРУППУ</b>" if target_id != message.from_user.id else ""
            
            # Убираем клавиатуру "Без текста" (если мы не в группе)
            current_kb = types.ReplyKeyboardRemove()
            await message.answer(f"✅ Задача сохранена {t_name}!", parse_mode="HTML", reply_markup=current_kb)
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    group_id = await clear_state_keep_group(state)
    if group_id:
        from keyboards import get_group_mode_keyboard
        # Если в группе - возвращаем меню группы
        await message.answer("Что дальше?", reply_markup=get_group_mode_keyboard())