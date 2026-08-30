from aiogram.fsm.state import State, StatesGroup


class OwnerStates(StatesGroup):
    waiting_studio_name = State()
    waiting_resource_name = State()
    waiting_hours = State()
    waiting_price = State()
    waiting_hours_edit = State()
    waiting_price_edit = State()
    waiting_extra_resource = State()


class BookingStates(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_consent = State()
