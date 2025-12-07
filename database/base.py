from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database.models import Base
import os

# Указываем путь к БД. Если мы в Докере, это будет важно.
# Пока сохраним локально в файле bot.db
DB_URL = "sqlite+aiosqlite:///bot.db"

engine = create_async_engine(DB_URL, echo=False)

# Фабрика сессий - через нее мы будем делать запросы
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    """Создает таблицы в БД, если их нет"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
