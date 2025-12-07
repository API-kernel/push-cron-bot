from aiogram import BaseMiddleware
from aiogram.types import Message

class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        # Проверяем, что это Сообщение и оно в Группе
        if isinstance(event, Message) and event.chat.type in ["group", "supergroup"]:
            
            # Проверяем, является ли сообщение Командой (начинается с /)
            # (Обычный текст мы не фильтруем, пусть общаются)
            text = event.text or event.caption or ""
            if text.startswith("/"):
                
                # Список команд, доступных всем (Whitelist)
                # Если хочешь закрыть ВСЁ - оставь список пустым
                public_commands = ["/help"] 
                
                command = text.split()[0].split("@")[0] # /add@bot -> /add
                
                if command not in public_commands:
                    # Проверяем права
                    member = await event.bot.get_chat_member(event.chat.id, event.from_user.id)
                    if member.status not in ["administrator", "creator"]:
                        await event.answer("⛔️ Эта команда доступна только администраторам.")
                        return # Прерываем выполнение, хендлер не сработает
        
        # Если всё ок - пропускаем дальше
        return await handler(event, data)