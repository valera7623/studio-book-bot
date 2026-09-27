from datetime import datetime, timedelta, timezone, time

from src.database.models.studio import TARIFF_PLUS, Resource, Studio
from src.database.models.user import User
from src.handlers.owner import (
    _begin_resource_edit,
    cb_days,
    cb_hall_manage,
    cb_hours,
    cb_off_hall,
    cb_off_hall_ok,
    cb_step,
    cb_weekday_toggle,
    owner_hours_edit,
    owner_price_edit,
    owner_resource_rename,
)
from src.keyboards.inline import (
    grid_keyboard,
    hall_manage_keyboard,
    owner_resource_pick_keyboard,
    slot_settings_keyboard,
    weekdays_keyboard,
)
from src.services.studios import list_active_resources
from src.services.tariffs import can_add_resource, count_resources
from src.services.outreach import owner_cheat_sheet
from src.states.booking import OwnerStates


class FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.replies: list[tuple[str, dict]] = []

    async def answer(self, text, **kwargs):
        self.replies.append((text, kwargs))

    async def edit_reply_markup(self, **kwargs):
        self.replies.append(("", kwargs))


class FakeCallback:
    def __init__(self, data: str):
        self.data = data
        self.message = FakeMessage()
        self.alerts: list[tuple] = []

    async def answer(self, *args, **kwargs):
        self.alerts.append((args, kwargs))


class FakeState:
    def __init__(self, **data):
        self._data = dict(data)
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def set_state(self, value):
        self.state = value

    async def clear(self):
        self._data.clear()
        self.state = None


async def _seed_two_halls(session):
    owner = User(
        telegram_id=5001,
        username="owner",
        first_name="Анна",
        language_code="ru",
    )
    session.add(owner)
    await session.flush()
    studio = Studio(
        slug="plus-studio",
        name="Плюс студия",
        owner_id=owner.id,
        owner_telegram_id=owner.telegram_id,
        tariff=TARIFF_PLUS,
        resource_limit=6,
        timezone="Europe/Moscow",
        subscription_until=datetime.now(timezone.utc) + timedelta(days=20),
    )
    session.add(studio)
    await session.flush()
    cyc = Resource(
        studio_id=studio.id,
        name="Циклорама",
        duration_min=60,
        slot_step_min=60,
        min_duration_min=60,
        buffer_min=5,
        timezone="Europe/Moscow",
        work_start=time(10, 0),
        work_end=time(22, 0),
        weekdays="1,2,3,4,5,6,7",
        price_rub=2500,
        weekend_price_rub=3000,
        night_price_rub=2000,
    )
    makeup = Resource(
        studio_id=studio.id,
        name="Грим",
        duration_min=60,
        slot_step_min=30,
        min_duration_min=60,
        buffer_min=10,
        timezone="Europe/Moscow",
        work_start=time(11, 0),
        work_end=time(20, 0),
        weekdays="1,2,3,4,5,6,7",
        price_rub=1500,
        weekend_price_rub=1800,
        night_price_rub=0,
    )
    session.add_all([cyc, makeup])
    await session.commit()
    await session.refresh(owner)
    await session.refresh(cyc)
    await session.refresh(makeup)
    return owner, cyc, makeup


def _kb_datas(markup) -> list[str]:
    return [btn.callback_data for row in markup.inline_keyboard for btn in row]


async def test_hours_edit_one_hall_does_not_change_other(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    makeup_hours = (makeup.work_start, makeup.work_end)
    makeup_price = makeup.price_rub

    state = FakeState(edit_resource_id=cyc.id)
    await owner_hours_edit(FakeMessage("09:00 21:00"), session, owner, state)

    await session.refresh(cyc)
    await session.refresh(makeup)
    assert cyc.work_start == time(9, 0)
    assert cyc.work_end == time(21, 0)
    assert (makeup.work_start, makeup.work_end) == makeup_hours
    assert makeup.price_rub == makeup_price


async def test_price_edit_one_hall_does_not_change_other(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    makeup_price = makeup.price_rub
    makeup_hours = (makeup.work_start, makeup.work_end)

    state = FakeState(edit_resource_id=cyc.id)
    await owner_price_edit(FakeMessage("4000"), session, owner, state)

    await session.refresh(cyc)
    await session.refresh(makeup)
    assert cyc.price_rub == 4000
    assert makeup.price_rub == makeup_price
    assert (makeup.work_start, makeup.work_end) == makeup_hours


async def test_slot_step_one_hall_does_not_change_other(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    makeup_step = makeup.slot_step_min

    callback = FakeCallback(f"ow:step:{cyc.id}:30")
    await cb_step(callback, session, owner)

    await session.refresh(cyc)
    await session.refresh(makeup)
    assert cyc.slot_step_min == 30
    assert makeup.slot_step_min == makeup_step
    datas = _kb_datas(callback.message.replies[0][1]["reply_markup"])
    assert f"ow:step:{cyc.id}:30" in datas


async def test_two_halls_hours_asks_which_resource(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    callback = FakeCallback("ow:hr")
    state = FakeState()
    await cb_hours(callback, session, owner, state)

    assert callback.message.replies
    text, kwargs = callback.message.replies[0]
    assert text == "Какой зал?"
    datas = _kb_datas(kwargs["reply_markup"])
    assert f"ow:hrp:{cyc.id}" in datas
    assert f"ow:hrp:{makeup.id}" in datas
    assert state.state is None


async def test_single_hall_hours_skips_pick(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    makeup.is_active = False
    await session.commit()

    callback = FakeCallback("ow:hr")
    state = FakeState()
    await cb_hours(callback, session, owner, state)

    assert state.state == OwnerStates.waiting_hours_edit
    assert state._data["edit_resource_id"] == cyc.id
    assert "Циклорама" in callback.message.replies[0][0]


async def test_begin_resource_edit_returns_only_hall(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    makeup.is_active = False
    await session.commit()
    callback = FakeCallback("ow:price")
    resource = await _begin_resource_edit(callback, session, owner, "ow:prp")
    assert resource is not None
    assert resource.id == cyc.id
    assert callback.message.replies == []


def test_slot_and_grid_keyboards_embed_resource_id():
    resource = Resource(id=42, name="Циклорама", slot_step_min=60, min_duration_min=60, buffer_min=5)
    slot_datas = _kb_datas(slot_settings_keyboard(resource))
    assert "ow:step:42:30" in slot_datas
    assert "ow:mind:42:120" in slot_datas
    assert "ow:buf:42:10" in slot_datas
    grid_datas = _kb_datas(grid_keyboard(42))
    assert "ow:prp:42" in grid_datas
    assert "ow:wknd:42" in grid_datas
    assert "ow:night:42" in grid_datas


def test_resource_pick_keyboard_prefix():
    halls = [
        Resource(id=1, name="Циклорама"),
        Resource(id=2, name="Грим"),
    ]
    datas = _kb_datas(owner_resource_pick_keyboard(halls, "ow:slp"))
    assert datas[:2] == ["ow:slp:1", "ow:slp:2"]


def test_cheat_sheet_mentions_hall_pick():
    text = owner_cheat_sheet()
    assert "выбрать зал" in text
    assert "Дни недели" in text
    assert "✏️ Залы" in text
    assert "для всех залов" not in text
    assert len(text) < 3500


async def test_weekday_toggle_one_hall_does_not_change_other(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    makeup_days = makeup.weekdays
    callback = FakeCallback(f"ow:wd:{cyc.id}:7")
    await cb_weekday_toggle(callback, session, owner)
    await session.refresh(cyc)
    await session.refresh(makeup)
    assert cyc.weekdays == "1,2,3,4,5,6"
    assert makeup.weekdays == makeup_days


async def test_cannot_disable_last_weekday(session):
    owner, cyc, _makeup = await _seed_two_halls(session)
    cyc.weekdays = "7"
    await session.commit()
    callback = FakeCallback(f"ow:wd:{cyc.id}:7")
    await cb_weekday_toggle(callback, session, owner)
    await session.refresh(cyc)
    assert cyc.weekdays == "7"
    assert any("Нужен хотя бы один день" in str(item) for item in callback.alerts)


async def test_two_halls_days_asks_which_resource(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    callback = FakeCallback("ow:days")
    await cb_days(callback, session, owner)
    text, kwargs = callback.message.replies[0]
    assert text == "Какой зал?"
    datas = _kb_datas(kwargs["reply_markup"])
    assert f"ow:wdp:{cyc.id}" in datas
    assert f"ow:wdp:{makeup.id}" in datas


def test_weekdays_keyboard_embeds_resource_id():
    resource = Resource(id=42, name="Циклорама", weekdays="1,2,3,4,5")
    datas = _kb_datas(weekdays_keyboard(resource))
    assert "ow:wd:42:6" in datas
    assert "ow:wd:42:7" in datas
    assert "ow:wd:42:1" in datas


def test_hall_manage_keyboard_callbacks():
    resource = Resource(id=7, name="Грим")
    datas = _kb_datas(hall_manage_keyboard(resource))
    assert "ow:ren:7" in datas
    assert "ow:off:7" in datas


async def test_rename_hall_updates_name(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    state = FakeState(edit_resource_id=cyc.id)
    await owner_resource_rename(FakeMessage("Циклорама 2"), session, owner, state)
    await session.refresh(cyc)
    await session.refresh(makeup)
    assert cyc.name == "Циклорама 2"
    assert makeup.name == "Грим"


async def test_deactivate_hall_hides_from_active(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    callback = FakeCallback(f"ow:ofok:{makeup.id}")
    await cb_off_hall_ok(callback, session, owner)
    await session.refresh(makeup)
    assert makeup.is_active is False
    active = await list_active_resources(session, cyc.studio_id)
    assert [r.id for r in active] == [cyc.id]
    assert await count_resources(session, cyc.studio_id) == 1
    ok, _ = await can_add_resource(session, await session.get(Studio, cyc.studio_id))
    assert ok


async def test_cannot_deactivate_last_hall(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    makeup.is_active = False
    await session.commit()
    callback = FakeCallback(f"ow:off:{cyc.id}")
    await cb_off_hall(callback, session, owner)
    await session.refresh(cyc)
    assert cyc.is_active is True
    assert any("последний зал" in str(item) for item in callback.alerts)


async def test_two_halls_manage_asks_which(session):
    owner, cyc, makeup = await _seed_two_halls(session)
    callback = FakeCallback("ow:hall")
    await cb_hall_manage(callback, session, owner)
    text, kwargs = callback.message.replies[0]
    assert text == "Какой зал?"
    datas = _kb_datas(kwargs["reply_markup"])
    assert f"ow:hlp:{cyc.id}" in datas
    assert f"ow:hlp:{makeup.id}" in datas
