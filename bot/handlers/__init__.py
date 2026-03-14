from aiogram import Dispatcher

from bot.handlers.admin import router as admin_router
from bot.handlers.common import router as common_router
from bot.handlers.lyrics import router as lyrics_router
from bot.handlers.search import router as search_router
from bot.handlers.settings import router as settings_router


def register_routers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(common_router)
    dispatcher.include_router(settings_router)
    dispatcher.include_router(lyrics_router)
    dispatcher.include_router(search_router)
    dispatcher.include_router(admin_router)
