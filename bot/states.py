from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    waiting_for_search_query = State()
    waiting_for_download_query = State()


class LyricsStates(StatesGroup):
    waiting_for_query = State()


class AdminStates(StatesGroup):
    waiting_for_broadcast_all = State()
    waiting_for_broadcast_groups = State()
