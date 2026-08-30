from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from src.database.models.booking import STATUS_CANCELLED, STATUS_HOLD, Booking
from src.database.models.studio import Resource, Studio
from src.database.models.user import User


def _slot_start() -> datetime:
    return datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


async def _seed_resource(session) -> Resource:
    owner = User(
        telegram_id=1001,
        username="owner",
        first_name="Анна",
        language_code="ru",
    )
    session.add(owner)
    await session.flush()

    studio = Studio(
        slug="demo-studio",
        name="Демо студия",
        owner_id=owner.id,
        owner_telegram_id=owner.telegram_id,
    )
    session.add(studio)
    await session.flush()

    resource = Resource(studio_id=studio.id, name="Циклорама")
    session.add(resource)
    await session.flush()
    return resource


async def test_two_active_holds_same_slot_rejected(session):
    resource = await _seed_resource(session)
    start = _slot_start()
    end = start + timedelta(hours=1)

    session.add(
        Booking(
            resource_id=resource.id,
            studio_id=resource.studio_id,
            client_telegram_id=2001,
            client_name="Клиент А",
            starts_at=start,
            ends_at=end,
            status=STATUS_HOLD,
            hold_expires_at=start,
        )
    )
    await session.commit()

    session.add(
        Booking(
            resource_id=resource.id,
            studio_id=resource.studio_id,
            client_telegram_id=2002,
            client_name="Клиент Б",
            starts_at=start,
            ends_at=end,
            status=STATUS_HOLD,
            hold_expires_at=start,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_cancelled_slot_can_be_rebooked(session):
    resource = await _seed_resource(session)
    start = _slot_start()
    end = start + timedelta(hours=1)

    first = Booking(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        client_telegram_id=2001,
        client_name="Клиент А",
        starts_at=start,
        ends_at=end,
        status=STATUS_CANCELLED,
    )
    session.add(first)
    await session.commit()

    second = Booking(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        client_telegram_id=2002,
        client_name="Клиент Б",
        starts_at=start,
        ends_at=end,
        status=STATUS_HOLD,
    )
    session.add(second)
    await session.commit()
    assert second.id is not None
