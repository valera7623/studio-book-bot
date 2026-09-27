from datetime import datetime, timedelta, timezone, time

from src.database.base import utcnow
from src.database.models.booking import STATUS_PAID, Booking
from src.database.models.studio import TARIFF_PLUS, TARIFF_STARTER, Resource, Studio
from src.database.models.user import User
from src.services.studios import list_active_resources
from src.services.tariffs import (
    can_create_booking,
    collect_due_subscription_notices,
    effective_tariff,
    subscription_downgrade_text,
    subscription_remind_text,
    sync_expired_subscription,
    tariff_cabinet_line,
)


async def _seed_studio(session, *, tariff=TARIFF_STARTER, until=None, halls=1):
    owner = User(telegram_id=61001, first_name="Анна", language_code="ru")
    session.add(owner)
    await session.flush()
    studio = Studio(
        slug="sub-studio",
        name="Студия",
        owner_id=owner.id,
        owner_telegram_id=owner.telegram_id,
        tariff=tariff,
        resource_limit=6 if tariff == TARIFF_PLUS else 1,
        subscription_until=until,
        timezone="Europe/Moscow",
    )
    session.add(studio)
    await session.flush()
    resources = []
    for i, name in enumerate(("Циклорама", "Грим")[:halls]):
        resource = Resource(
            studio_id=studio.id,
            name=name,
            duration_min=60,
            slot_step_min=60,
            min_duration_min=60,
            buffer_min=0,
            timezone="Europe/Moscow",
            work_start=time(10, 0),
            work_end=time(12, 0),
            weekdays="1,2,3,4,5,6,7",
            price_rub=1000,
        )
        session.add(resource)
        resources.append(resource)
    await session.commit()
    await session.refresh(studio)
    for resource in resources:
        await session.refresh(resource)
    return studio, resources


async def _fill_month(session, studio, resource, n: int) -> None:
    start = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(n):
        session.add(
            Booking(
                resource_id=resource.id,
                studio_id=studio.id,
                client_telegram_id=7000 + i,
                client_name="x",
                starts_at=start + timedelta(days=i),
                ends_at=start + timedelta(days=i, hours=1),
                status=STATUS_PAID,
            )
        )
    await session.commit()


async def test_expired_starter_hits_free_limit_and_asks_to_renew(session):
    now = utcnow()
    studio, resources = await _seed_studio(
        session, until=now - timedelta(days=1)
    )
    await _fill_month(session, studio, resources[0], 30)
    ok, reason = await can_create_booking(session, studio)
    assert ok is False
    assert "истекла" in reason.lower()
    assert "продлите" in reason.lower()
    await session.refresh(studio)
    assert studio.tariff == "free"


async def test_active_starter_not_limited(session):
    now = utcnow()
    studio, resources = await _seed_studio(
        session, until=now + timedelta(days=10)
    )
    await _fill_month(session, studio, resources[0], 30)
    ok, _ = await can_create_booking(session, studio)
    assert ok is True
    assert effective_tariff(studio, now) == TARIFF_STARTER


async def test_downgrade_plus_deactivates_extra_hall(session):
    now = utcnow()
    studio, resources = await _seed_studio(
        session, tariff=TARIFF_PLUS, until=now - timedelta(hours=1), halls=2
    )
    changed, extra = await sync_expired_subscription(session, studio, now)
    await session.commit()
    assert changed is True
    assert extra == ["Грим"]
    await session.refresh(studio)
    await session.refresh(resources[1])
    assert studio.tariff == "free"
    active = await list_active_resources(session, studio.id)
    assert [r.name for r in active] == ["Циклорама"]
    assert "Продлить" in subscription_downgrade_text(studio, extra)


async def test_remind_three_days_before_expiry(session):
    now = utcnow()
    studio, _ = await _seed_studio(session, until=now + timedelta(days=2))
    due = await collect_due_subscription_notices(session, now)
    assert [(s.id, kind) for s, kind in due] == [(studio.id, "remind")]
    assert "3 дней" in subscription_remind_text(studio)


async def test_no_remind_when_far_or_already_sent(session):
    now = utcnow()
    studio, _ = await _seed_studio(session, until=now + timedelta(days=10))
    due = await collect_due_subscription_notices(session, now)
    assert due == []
    studio.subscription_until = now + timedelta(days=2)
    studio.subscription_reminded_at = now
    await session.commit()
    due = await collect_due_subscription_notices(session, now)
    assert due == []


async def test_collect_downgrade_once(session):
    now = utcnow()
    studio, _ = await _seed_studio(session, until=now - timedelta(days=1))
    due = await collect_due_subscription_notices(session, now)
    assert due[0][1] == "downgrade"
    studio.subscription_downgrade_notice_at = now
    studio.tariff = "free"
    await session.commit()
    due = await collect_due_subscription_notices(session, now)
    assert due == []


def test_cabinet_line_expired():
    now = utcnow()
    studio = Studio(
        slug="x",
        name="x",
        owner_id=1,
        owner_telegram_id=1,
        tariff=TARIFF_STARTER,
        subscription_until=now - timedelta(days=1),
    )
    line = tariff_cabinet_line(studio, now)
    assert "Free" in line
    assert "истекла" in line
