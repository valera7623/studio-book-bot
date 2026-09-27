from datetime import date, datetime, timedelta, timezone

from src.database.models.booking import STATUS_CANCELLED, STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.studio import Studio
from src.database.models.user import User
from src.handlers.owner import cb_bookings, cb_bookings_day, cb_bookings_page, owner_booking_date
from src.keyboards.inline import bookings_keyboard
from src.services.bookings_list import (
    MODE_ALL,
    MODE_CANCELLED,
    MODE_DATE,
    MODE_TODAY,
    bookings_callback,
    bookings_heading,
    format_booking_line,
    format_cancel_reason,
    list_owner_bookings,
    parse_owner_date,
)
from src.states.booking import OwnerStates
from tests.test_booking import _seed_resource
from tests.test_owner_resource_settings import FakeCallback, FakeState


class _Msg:
    def __init__(self):
        self.replies: list[tuple[str, dict]] = []
        self.edits: list[tuple[str, dict]] = []

    async def answer(self, text, **kwargs):
        self.replies.append((text, kwargs))

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))

    async def edit_reply_markup(self, **kwargs):
        self.replies.append(("", kwargs))


class _Cb(FakeCallback):
    def __init__(self, data: str):
        super().__init__(data)
        self.message = _Msg()


def _when(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)


async def _add_booking(session, resource, starts_at, *, status=STATUS_HOLD, name="Клиент", reason=None):
    booking = Booking(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        client_telegram_id=3001,
        client_name=name,
        client_phone="+79990001122",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        status=status,
        cancel_reason=reason,
    )
    session.add(booking)
    await session.flush()
    return booking


async def _owner(session, resource) -> User:
    studio = await session.get(Studio, resource.studio_id)
    return await session.get(User, studio.owner_id)


async def test_parse_owner_date():
    today = date(2026, 9, 27)
    assert parse_owner_date("27.09", today=today) == today
    assert parse_owner_date("27.09.2026", today=today) == today
    assert parse_owner_date("2026-09-01", today=today) == date(2026, 9, 1)
    assert parse_owner_date("нет", today=today) is None


def test_format_cancel_reason():
    assert format_cancel_reason("hold_expired") == "hold истёк"
    assert format_cancel_reason("owner:owner_cancel") == "владелец"
    assert format_cancel_reason("client:late_cancel") == "клиент, поздно"
    assert format_cancel_reason("client:free_cancel") == "клиент, в срок"


def test_bookings_keyboard_filters_and_pages():
    markup = bookings_keyboard(
        [(7, "Зал 12:00", "hold"), (8, "Зал 13:00", "paid")],
        mode="a",
        page=0,
        pages=3,
    )
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert "ow:bk:t:0" in data
    assert "ow:bk:c:0" in data
    assert "ow:bkp" in data
    assert "ow:bk:a:1" in data
    assert "ow:bkn" in data
    assert "ow:ok:7" in data
    assert "ow:c:8" in data
    assert any(text.startswith("· Все") for text in labels)
    assert all(len(item) <= 64 for item in data)

    cancelled = bookings_keyboard(
        [(9, "Зал 10:00", "cancelled")],
        mode="c",
        page=0,
        pages=1,
    )
    cdata = [btn.callback_data for row in cancelled.inline_keyboard for btn in row]
    assert "ow:ok:9" not in cdata
    assert "ow:c:9" not in cdata
    assert "ow:bk:c:0" in cdata

    dated = bookings_keyboard([], mode="d", page=0, pages=1, day=date(2026, 9, 27))
    ddata = [btn.callback_data for row in dated.inline_keyboard for btn in row]
    dlabels = [btn.text for row in dated.inline_keyboard for btn in row]
    assert any("27.09" in text for text in dlabels)
    assert "ow:bkp" in ddata
    assert bookings_callback("d", 2, date(2026, 9, 27)) == "ow:bkd:2026-09-27:2"
    assert len(bookings_callback("d", 99, date(2026, 9, 27))) <= 64


async def test_list_paginates_and_skips_past(session):
    resource = await _seed_resource(session, slug="bk-page", telegram_id=13001)
    now = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)
    today = date(2026, 9, 27)
    await _add_booking(session, resource, _when(date(2026, 9, 20)), name="Старая")
    for hour in range(10, 15):
        await _add_booking(session, resource, _when(today, hour), name=f"Ч{hour}")
    await session.commit()

    first = await list_owner_bookings(
        session,
        resource.studio_id,
        mode=MODE_ALL,
        page=0,
        tz_name="Europe/Moscow",
        now=now,
        page_size=3,
    )
    assert first.total == 5
    assert first.pages == 2
    assert len(first.rows) == 3
    assert first.rows[0].client_name == "Ч10"

    second = await list_owner_bookings(
        session,
        resource.studio_id,
        mode=MODE_ALL,
        page=1,
        tz_name="Europe/Moscow",
        now=now,
        page_size=3,
    )
    assert len(second.rows) == 2
    assert second.page == 1


async def test_list_filters_by_date_and_cancelled(session):
    resource = await _seed_resource(session, slug="bk-date", telegram_id=13002)
    now = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)
    day_a = date(2026, 9, 28)
    day_b = date(2026, 10, 1)
    keep = await _add_booking(session, resource, _when(day_a), name="НаА", status=STATUS_PAID)
    await _add_booking(session, resource, _when(day_b), name="НаБ")
    await _add_booking(
        session,
        resource,
        _when(day_a, 15),
        name="Сняли",
        status=STATUS_CANCELLED,
        reason="client:free_cancel",
    )
    await session.commit()

    only_a = await list_owner_bookings(
        session,
        resource.studio_id,
        mode=MODE_DATE,
        day=day_a,
        tz_name="UTC",
        now=now,
    )
    assert [row.client_name for row in only_a.rows] == ["НаА"]
    assert only_a.total == 1

    today_empty = await list_owner_bookings(
        session,
        resource.studio_id,
        mode=MODE_TODAY,
        tz_name="UTC",
        now=now,
    )
    assert today_empty.total == 0

    cancelled = await list_owner_bookings(
        session,
        resource.studio_id,
        mode=MODE_CANCELLED,
        tz_name="UTC",
        now=now,
    )
    assert cancelled.total == 1
    assert cancelled.rows[0].client_name == "Сняли"
    line = format_booking_line(cancelled.rows[0], "UTC", cancelled=True)
    assert "Сняли" in line
    assert "клиент, в срок" in line
    assert keep.id not in {row.id for row in cancelled.rows}
    heading = bookings_heading(cancelled)
    assert "Отмены" in heading


async def test_cb_bookings_renders_filters(session):
    resource = await _seed_resource(session, slug="bk-ui", telegram_id=13003)
    now_day = date(2026, 10, 5)
    await _add_booking(session, resource, _when(now_day, 11), name="Анна")
    await _add_booking(
        session,
        resource,
        _when(now_day, 14),
        name="Отмена",
        status=STATUS_CANCELLED,
        reason="owner:owner_cancel",
    )
    await session.commit()
    owner = await _owner(session, resource)
    cb = _Cb("ow:book")
    state = FakeState()
    await cb_bookings(cb, session, owner, state)
    text, kwargs = cb.message.edits[0]
    assert "Анна" in text
    assert "Отмена" not in text
    markup = kwargs["reply_markup"]
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "ow:bk:c:0" in data

    cb2 = _Cb("ow:bk:c:0")
    await cb_bookings_page(cb2, session, owner, FakeState())
    cancel_text, _ = cb2.message.edits[0]
    assert "Отмена" in cancel_text
    assert "владелец" in cancel_text

    cb3 = _Cb(f"ow:bkd:{now_day.isoformat()}:0")
    await cb_bookings_day(cb3, session, owner, FakeState())
    day_text, _ = cb3.message.edits[0]
    assert "Анна" in day_text


async def test_owner_booking_date_fsm(session):
    resource = await _seed_resource(session, slug="bk-fsm", telegram_id=13004)
    target = date(2026, 11, 2)
    await _add_booking(session, resource, _when(target), name="Ноябрь")
    await session.commit()
    owner = await _owner(session, resource)
    state = FakeState()
    await state.set_state(OwnerStates.waiting_booking_date)
    msg = _Msg()
    msg.text = "02.11.2026"
    await owner_booking_date(msg, session, owner, state)
    assert state.state is None
    assert "Ноябрь" in msg.replies[0][0]
