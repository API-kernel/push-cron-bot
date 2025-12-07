from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# --- Главное меню выбора типа (без изменений) ---
def get_presets_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🗓 Ежедневно", callback_data="preset_daily")],
        [InlineKeyboardButton(text="📅 Еженедельно", callback_data="preset_weekly")],
        [InlineKeyboardButton(text="📆 Ежемесячно", callback_data="preset_monthly")],
        [InlineKeyboardButton(text="🎉 Ежегодно", callback_data="preset_yearly")],
        [InlineKeyboardButton(text="🤓 Свой формат (Cron)", callback_data="preset_custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- Дни недели (С МУЛЬТИВЫБОРОМ) ---
# --- Дни недели (С ИМЕНАМИ ВМЕСТО ЦИФР) ---
def get_weekdays_keyboard(selected_days=None):
    if selected_days is None:
        selected_days = []

    # Используем MON, TUE... чтобы избежать путаницы 0=Вс vs 0=Пн
    days_config = [
        ("Пн", "MON"), ("Вт", "TUE"), ("Ср", "WED"), ("Чт", "THU"),
        ("Пт", "FRI"), ("Сб", "SAT"), ("Вс", "SUN")
    ]
    
    keyboard = []
    row = []
    
    for text, value in days_config:
        # Если день в списке, добавляем галочку
        if value in selected_days:
            btn_text = f"✅ {text}"
        else:
            btn_text = text
            
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"weekday_{value}"))
        
        if len(row) == 4:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(text="Готово ➡️", callback_data="weekday_done")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- Месяцы (С МУЛЬТИВЫБОРОМ) ---
def get_months_keyboard(selected_months=None):
    if selected_months is None:
        selected_months = []
    
    selected_months = [str(m) for m in selected_months]

    months_config = [
        ("Янв", "1"), ("Фев", "2"), ("Мар", "3"), ("Апр", "4"),
        ("Май", "5"), ("Июн", "6"), ("Июл", "7"), ("Авг", "8"),
        ("Сен", "9"), ("Окт", "10"), ("Ноя", "11"), ("Дек", "12")
    ]
    
    keyboard = []
    row = []
    
    for text, value in months_config:
        if value in selected_months:
            btn_text = f"✅ {text}"
        else:
            btn_text = text
            
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"month_{value}"))
        
        if len(row) == 4:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(text="Готово ➡️", callback_data="month_done")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ... (старые функции) ...

def get_group_mode_keyboard():
    """Меню для режима управления группой (Только выход)"""
    kb = [
        [KeyboardButton(text="🔙 Выйти из режима группы")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)