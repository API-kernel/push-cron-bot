from aiogram import Router, F, types
from urllib.parse import quote
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, update

from services.cron_manager import add_task 
from database.base import async_session
from database.models import User, Task, SharedLink
from keyboards import get_group_mode_keyboard

print("LOADED: common")

# Создаем роутер для этого модуля
router = Router()

# ================= СОСТОЯНИЯ (Общие для всех модулей) =================
class TaskStates(StatesGroup):
    # Добавление
    waiting_for_preset = State()
    waiting_for_time = State()
    waiting_for_weekday = State()
    waiting_for_day_month = State()
    waiting_for_month = State()
    adding_cron = State()
    adding_text = State()
    
    # Редактирование
    waiting_for_edit_id = State()
    editing_select_action = State()
    editing_cron = State()
    editing_text = State()

    # Ветки редактирования
    editing_text_input = State() # Ввод нового текста
    
    # Ветка времени (дублирует логику Adding, но для Edit)
    editing_preset_choice = State() 
    editing_time_input = State()
    editing_weekday = State()
    editing_month = State()
    editing_day_month = State()
    editing_cron_input = State()
    
    # Удаление и Пауза
    waiting_for_delete_id = State()
    waiting_for_delete_all = State()
    waiting_for_pause_id = State()
    waiting_for_resume_id = State()
    waiting_for_media_note = State()
    waiting_for_share_id = State() 
    
    # Настройки и Импорт
    waiting_for_timezone = State()
    waiting_for_import = State()

# ================= ХЕЛПЕРЫ (HELPERS) =================

async def clear_state_keep_group(state: FSMContext):
    """Очищает состояние, но сохраняет активную группу (Sticky Session)"""
    data = await state.get_data()
    group_id = data.get("active_group_id")
    await state.clear()
    if group_id:
        await state.update_data(active_group_id=group_id)
    return group_id

async def get_target_id(event: types.Message | types.CallbackQuery, state: FSMContext):
    """Возвращает ID группы (если мы в режиме) или ID юзера"""
    data = await state.get_data()
    group_id = data.get("active_group_id")
    if group_id:
        return group_id
    
    # Если группы нет, берем ID юзера
    return event.from_user.id

async def get_target_name(state: FSMContext):
    """Возвращает текст для сообщений: ' (для ГРУППЫ)' или ''"""
    data = await state.get_data()
    return " (для <b>ГРУППЫ</b>)" if data.get("active_group_id") else ""

async def get_real_task_by_number(session, target_id: int, task_number: int):
    """Переводит порядковый номер (1, 2...) в реальный ID задачи"""
    if task_number < 1: return None
    query = select(Task).where(Task.user_id == target_id).order_by(Task.id)
    result = await session.execute(query)
    tasks = result.scalars().all()
    if task_number <= len(tasks): return tasks[task_number - 1]
    return None

async def apply_timezone(message: types.Message, offset_str: str, target_id: int):
    """Применяет часовой пояс к target_id (юзеру или группе)"""
    try:
        offset = int(offset_str)
        if not (-12 <= offset <= 14): raise ValueError
    except ValueError:
        await message.answer("❌ Нужно целое число от -12 до 14.", parse_mode="HTML")
        return
    
    posix_sign = -1 * offset
    tz_name = f"Etc/GMT{posix_sign:+d}"

    async with async_session() as session:
        # Проверяем, есть ли запись в таблице users
        res = await session.execute(select(User).where(User.user_id == target_id))
        if not res.scalar_one_or_none():
            session.add(User(user_id=target_id))
        
        stmt = update(User).where(User.user_id == target_id).values(timezone=tz_name)
        await session.execute(stmt)
        await session.commit()
    
    target_text = " для <b>ГРУППЫ</b>" if target_id != message.from_user.id else ""
    await message.answer(f"✅ Часовой пояс{target_text} установлен: <b>UTC{offset:+d}</b>", parse_mode="HTML")

# ================= БАЗОВЫЕ КОМАНДЫ =================

@router.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear() # Полный сброс при старте
    user_id = message.from_user.id
    
    # Регистрация юзера
    async with async_session() as session:
        res = await session.execute(select(User).where(User.user_id == user_id))
        if not res.scalar_one_or_none():
            session.add(User(user_id=user_id))
            await session.commit()

    # Проверка Deep Link (Режим Группы)
    args = command.args
    if args and args.startswith("addgroup_"):
        safe_group_id = args.replace("addgroup_", "")
        try:
            real_group_id = int(safe_group_id.replace("m", "-"))
        except ValueError:
            await message.answer("❌ Ошибка ссылки.")
            return

        # ВХОДИМ В РЕЖИМ ГРУППЫ
        await state.update_data(active_group_id=real_group_id)
        
        await message.answer(
            f"🔧 <b>Режим управления группой (ID {real_group_id})</b>\n\n"
            "Теперь любые команды из Меню применяются к <b>ЭТОЙ ГРУППЕ</b>.\n"
            "Нажми кнопку внизу, чтобы выйти.", 
            reply_markup=get_group_mode_keyboard(), # Тут теперь только кнопка Выход
            parse_mode="HTML"
        )
        return
    elif args and args.startswith("share_"):
        token = args.replace("share_", "")
                
        async with async_session() as session:
            res = await session.execute(select(SharedLink).where(SharedLink.token == token))
            shared_task = res.scalar_one_or_none()
            
            if not shared_task:
                await message.answer("❌ Ссылка устарела или не существует.")
                return
            
            # Предпросмотр
            type_icon = "📄"
            if shared_task.content_type == "photo": type_icon = "🖼"
            elif shared_task.content_type == "voice": type_icon = "🎤"
            
            text_preview = shared_task.message_text or "(Без текста)"
            
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="✅ Добавить себе", callback_data=f"accept_share_{token}")]
            ])
            
            readable_cron = humanize_cron(shared_task.cron_expression)
            cron_display = f"⚙️ Расписание: <code>{shared_task.cron_expression}</code>" if readable_cron == shared_task.cron_expression else f"⚙️ Расписание: <b>{readable_cron}</b>"
            
            await message.answer(
                f"🎁 <b>Вам прислали задачу!</b>\n\n"
                f"{cron_display}\n"
                f"{type_icon} Текст: <i>{text_preview}</i>\n\n"
                "Хотите добавить её в свой список?",
                parse_mode="HTML",
                reply_markup=kb
            )
        return
    await message.answer(
        "Привет! Я CronBot.\nТвой пояс по умолчанию: Екатеринбург (UTC+5).\n"
        "Жми /help для списка команд.",
        reply_markup=types.ReplyKeyboardRemove()
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    await clear_state_keep_group(state)
    text = (
        "🤖 <b>RemindMe | Справка</b>\n\n"
        
        "✨ <b>Как пользоваться:</b>\n"
        "1. <b>Создать:</b> Жми /add. Я понимаю текст, фото 🖼, видео 📹, голосовые 🎤 и стикеры 👻.\n"
        "2. <b>Управлять:</b> Жми /list. Нажми на номер задачи, чтобы изменить, удалить или поставить её на паузу.\n\n"
        
        "👥 <b>Группы:</b>\n"
        "Добавь меня в чат и нажми /add. Я пришлю ссылку для настройки расписания группы в ЛС.\n\n"
        
        "🌍 <b>Настройки:</b>\n"
        "• /timezone — Настройка часового пояса (по умолчанию Екатеринбург UTC+5).\n\n"
        
        "📦 <b>Перенос данных:</b>\n"
        "• /export — Скачать резервную копию.\n"
        "• /import — Загрузить задачи из файла.\n\n"
        
        "<i>Совет: В /list можно нажать кнопку «Поделиться», чтобы отправить задачу другу.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("timezone"))
async def cmd_timezone(message: types.Message, state: FSMContext):
    target_id = await get_target_id(message, state)
    await clear_state_keep_group(state)
    
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        await apply_timezone(message, args[1], target_id)
        return
    
    # Получаем текущую зону
    async with async_session() as session:
        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        current_tz = res.scalar() or "UTC"
        # Красивый вывод (Etc/GMT-3 -> UTC+3)
        try:
            if "Etc/GMT" in current_tz:
                offset = int(current_tz.replace("Etc/GMT", ""))
                display_tz = f"UTC{-offset:+d}" # Инверсия знака
            else:
                display_tz = current_tz
        except:
            display_tz = current_tz
    
    t_name = await get_target_name(state)
    await message.answer(
        f"🌍 Текущий пояс{t_name}: <b>{display_tz}</b>\n\n"
        "Чтобы изменить, введите смещение от UTC числом (например 3):", 
        parse_mode="HTML"
    )
    await state.set_state(TaskStates.waiting_for_timezone)

@router.message(TaskStates.waiting_for_timezone, ~F.text.startswith("/"))
async def process_tz(message: types.Message, state: FSMContext):
    target_id = await get_target_id(message, state)
    await apply_timezone(message, message.text, target_id)
    await clear_state_keep_group(state)

# --- МЕНЮ РЕЖИМА ГРУППЫ ---
@router.message(F.text == "🔙 Выйти из режима группы")
async def exit_group_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Вы вышли из режима группы.", reply_markup=types.ReplyKeyboardRemove())

# ... (код функции exit_group_mode) ...

# ================= CATCH-ALL (ЛОВУШКА) =================
# Этот хендлер сработает, только если ни один другой не подошел.

@router.message(
    F.chat.type == "private",  # Только в личке
    StateFilter(None)          # Только если юзер НЕ занят вводом (нет FSM)
)
async def unknown_message(message: types.Message):
    # Кнопка, чтобы юзер не потерялся
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="ℹ️ Помощь / Меню", callback_data="help_call")]
    ])
    
    await message.answer(
        "Я не понимаю это сообщение 🤷‍♂️\n"
        "Выберите команду из Меню или нажмите кнопку ниже.",
        reply_markup=kb
    )

@router.callback_query(F.data == "help_call")
async def help_callback(callback: types.CallbackQuery):
    await callback.message.answer("Нажмите кнопку [Меню] слева внизу или введите /help")
    await callback.answer()


@router.callback_query(F.data.startswith("accept_share_"))
async def process_share_accept(callback: types.CallbackQuery, state: FSMContext):
    token = callback.data.replace("accept_share_", "")
    
    data = await state.get_data()
    group_id = data.get("active_group_id")
    target_id = group_id if group_id else callback.from_user.id 
    
    from database.models import SharedLink 
    from services.cron_manager import add_task
    
    async with async_session() as session:
        res = await session.execute(select(SharedLink).where(SharedLink.token == token))
        shared_task = res.scalar_one_or_none()
        
        if not shared_task:
            await callback.answer("Ссылка недействительна.", show_alert=True)
            return

        res = await session.execute(select(User.timezone).where(User.user_id == target_id))
        user_tz = res.scalar() or "Asia/Yekaterinburg"
        
        try:
            await add_task(
                bot=callback.message.bot, 
                session=session, 
                user_id=target_id,
                cron_exp=shared_task.cron_expression, # Берем из снепшота
                text=shared_task.message_text,
                timezone_str=user_tz,
                content_type=shared_task.content_type,
                file_id=shared_task.file_id
            )
            
            await callback.message.edit_text(f"✅ Задача успешно добавлена!")
        except Exception as e:
            await callback.message.edit_text(f"❌ Ошибка: {e}")
            
    await callback.answer()

def validate_time_format(time_str: str):
    from datetime import datetime
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False

# Словари для перевода
DOW_RU = {
    'MON': 'Пн', 'TUE': 'Вт', 'WED': 'Ср', 'THU': 'Чт',
    'FRI': 'Пт', 'SAT': 'Сб', 'SUN': 'Вс',
    '0': 'Вс', '1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'
}

MONTHS_RU = {
    '1': 'Января', '2': 'Февраля', '3': 'Марта', '4': 'Апреля',
    '5': 'Мая', '6': 'Июня', '7': 'Июля', '8': 'Августа',
    '9': 'Сентября', '10': 'Октября', '11': 'Ноября', '12': 'Декабря'
}

def humanize_cron(expression: str) -> str:
    """Превращает '0 9 * * MON' в 'Каждый Пн в 09:00'"""
    parts = expression.strip().split()
    if len(parts) != 5:
        return expression

    minute, hour, day, month, dow = parts

    # 1. Проверка ВРЕМЕНИ
    # Если время сложное (*/5, 9-18), мы не сможем его красиво написать
    if not (minute.isdigit() and hour.isdigit()):
        return expression
    
    time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"

    # 2. ЕЖЕДНЕВНО: * * *
    if day == '*' and month == '*' and dow == '*':
        return f"🗓 Ежедневно в {time_str}"

    # 3. ЕЖЕНЕДЕЛЬНО: * * MON,WED (или цифры)
    # Здесь допускаются только запятые (MON,WED), но не тире (MON-FRI)
    if day == '*' and month == '*' and dow != '*':
        if '-' in dow or '/' in dow: return expression # Сложный паттерн дней
        
        days_en = dow.split(',')
        days_ru = []
        for d in days_en:
            # Если d это не MON/TUE и не цифра - это что-то странное
            name = DOW_RU.get(d)
            if not name: return expression # Не смогли перевести
            days_ru.append(name)
            
        return f"📅 {', '.join(days_ru)} в {time_str}"

    # 4. ЕЖЕМЕСЯЧНО: 15 * *
    if day != '*' and month == '*' and dow == '*':
        if day.upper() == 'L':
            return f"📆 В последний день месяца в {time_str}"
        if not day.isdigit(): return expression # Если день это "1-5", показываем крон
        return f"📆 Каждое {day}-е число в {time_str}"

    # 5. ЕЖЕГОДНО: 1 1 *
    if day != '*' and month != '*' and dow == '*':
        if not (day.isdigit() and month.isdigit()): return expression
        
        month_name = MONTHS_RU.get(month)
        if not month_name: return expression
        
        return f"🎉 Каждый год {day} {month_name} в {time_str}"

    # Если ничего не подошло
    return expression

def get_share_text(task: Task) -> str:
    """Генерирует и кодирует текст для share-ссылки."""
    readable_cron = humanize_cron(task.cron_expression)
    share_text_parts = [f"{readable_cron}", task.message_text]
    share_text = "\r\n".join(filter(None, share_text_parts))
    return quote(share_text)