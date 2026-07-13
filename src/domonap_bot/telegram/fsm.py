from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_grant_admin_id = State()
