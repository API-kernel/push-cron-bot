from aiogram import Router

# Импортируем роутеры из модулей
from .common import router as common_router
from .adding import router as adding_router
from .list_view import router as list_view_router
from .task_actions import router as task_actions_router
from .backup import router as backup_router

# Создаем главный роутер
router = Router()

# Подключаем роутеры.
# ВАЖНО: common_router подключаем ПОСЛЕДНИМ, потому что в нем мы сейчас разместим "ловушку" для всех остальных сообщений.
router.include_router(adding_router)
router.include_router(list_view_router)
router.include_router(task_actions_router)
router.include_router(backup_router)
router.include_router(common_router)