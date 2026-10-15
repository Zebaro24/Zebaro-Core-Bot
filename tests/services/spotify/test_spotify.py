import sys
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock()

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db import sql
from src.interfaces.tg.handlers.admin.spotify import parse_adjustment, parse_day
from src.interfaces.tg.keyboards.spotify import sender_key
from src.services.spotify import ledger, repo, schedule, sync
from src.services.spotify.models import Adjustment, Charge, JarTransaction, Member
from src.services.spotify.report import Money

TZ = ZoneInfo("Europe/Berlin")


def _ts(day: date, hour: int = 12) -> int:
    return int(datetime(day.year, day.month, day.day, hour, tzinfo=TZ).timestamp())


def _member(member_id: int, owner: bool = False, joined: date = date(2022, 9, 1), left: date | None = None) -> Member:
    return Member(
        id=member_id, name=f"m{member_id}", is_owner=owner, joined_on=joined, left_on=left, invite_code=str(member_id)
    )


def _charge(day: date, amount: int, price: int = 799, charge_id: str | None = None) -> Charge:
    return Charge(id=charge_id or f"c{day}", time=_ts(day), amount=amount, operation_amount=price, currency_code=840)


def _topup(member_id: int | None, amount: int, day: date, kind: str = "topup") -> JarTransaction:
    return JarTransaction(
        id=f"t{member_id}{day}{amount}", time=_ts(day), amount=amount, balance=0, kind=kind, member_id=member_id
    )


# ── ledger ───────────────────────────────────────────────────────────────────


def test_split_gives_the_remainder_to_the_owner():
    members = [_member(2), _member(1, owner=True), _member(3)]
    assert ledger.split(1000, members) == {1: 334, 2: 333, 3: 333}
    assert sum(ledger.split(36146, [*members, _member(4), _member(5), _member(6)]).values()) == 36146


def test_split_without_the_owner_gives_it_to_the_earliest():
    assert ledger.split(10, [_member(5), _member(3), _member(4)]) == {3: 4, 4: 3, 5: 3}
    assert ledger.split(10, []) == {}


def test_charges_are_shared_among_members_active_that_day():
    owner = _member(1, owner=True)
    founder = _member(2)
    late = _member(3, joined=date(2023, 1, 13))
    gone = _member(4, left=date(2022, 12, 13))
    charges = [_charge(date(2022, 12, 12), 400), _charge(date(2023, 1, 12), 300), _charge(date(2023, 2, 12), 300)]
    book = ledger.build([owner, founder, late, gone], charges, [], [], TZ)
    assert book[4].owed == 133  # only December, with three people
    assert book[3].owed == 100  # only February, with three
    assert book[2].owed == 133 + 150 + 100
    assert book[1].owed == 134 + 150 + 100  # the December kopeck
    assert book[2].charges == 3 and book[3].charges == 1


def test_balance_counts_topups_and_adjustments_but_not_withdrawals_or_ignored():
    member = _member(2)
    ignored = _topup(2, 5000, date(2022, 10, 2))
    ignored.ignored = True
    transactions = [
        _topup(2, 6000, date(2022, 10, 1)),
        ignored,
        _topup(None, 9000, date(2022, 10, 3)),  # unknown sender
        _topup(None, -30000, date(2022, 10, 4), kind="withdrawal"),
    ]
    adjustments = [Adjustment(member_id=2, amount=-1000, note="", time=0)]
    book = ledger.build([member], [_charge(date(2022, 10, 12), 3000)], transactions, adjustments, TZ)
    assert book[2].topups == 6000
    assert book[2].paid == 5000
    assert book[2].balance == 2000


def test_months_covered_and_to_pay():
    assert ledger.months_covered(18000, 6000) == 3
    assert ledger.months_covered(-100, 6000) == 0
    assert ledger.to_pay(-1500, 6000) == 7500
    assert ledger.to_pay(9000, 6000) == 0


# ── schedule ─────────────────────────────────────────────────────────────────


def test_next_charge_follows_the_billing_day():
    assert schedule.next_charge(date(2026, 10, 15), date(2026, 10, 12)) == date(2026, 11, 12)
    assert schedule.next_charge(date(2026, 10, 5), date(2026, 9, 12)) == date(2026, 10, 12)
    # Late: this month's charge has not come yet — the day stays in the past.
    assert schedule.next_charge(date(2026, 10, 14), date(2026, 9, 12)) == date(2026, 10, 12)
    assert schedule.next_charge(date(2026, 12, 20), date(2026, 12, 12)) == date(2027, 1, 12)
    assert schedule.next_charge(date(2026, 1, 31), date(2026, 1, 31)) == date(2026, 2, 28)
    assert schedule.next_charge(date(2026, 10, 1), None) == date(2026, 10, 12)


def test_due_reminders():
    upcoming, last = date(2026, 11, 12), date(2026, 10, 12)
    assert schedule.due(date(2026, 11, 9), schedule.MORNING, upcoming, last) == {"before"}
    assert schedule.due(date(2026, 11, 9), schedule.EVENING, upcoming, last) == set()
    assert schedule.due(date(2026, 11, 11), schedule.EVENING, upcoming, last) == {"before"}
    assert schedule.due(date(2026, 10, 15), schedule.MORNING, upcoming, last) == {"debt"}
    assert schedule.due(date(2026, 10, 20), schedule.MORNING, upcoming, last) == set()


def test_forecast_and_markup():
    measured = schedule.markup(36146, 799, 45.0)
    assert measured == pytest.approx(36146 / 799 / 45.0)
    result = schedule.forecast(date(2026, 11, 12), 799, 45.0, measured)
    assert result.amount == 36146
    assert schedule.markup(100, 799, None) == 1.0


def test_money_advice():
    assert Money(card=40000, jar=0).advice(36000) == ("ok", 0)
    assert Money(card=10000, jar=90000).advice(36000) == ("withdraw", 26000)
    assert Money(card=10000, jar=6000).advice(36000) == ("short", 20000)
    assert Money().advice(36000) == ("unknown", 0)


# ── parsing ──────────────────────────────────────────────────────────────────


def test_classify_jar_items():
    assert sync.classify({"amount": 5000, "description": "Від: Олександр Яковенко"}) == ("topup", "Олександр Яковенко")
    assert sync.classify({"amount": 5000, "description": "З чорної картки"}) == ("own", None)
    assert sync.classify({"amount": -30000, "description": "На чорну картку"}) == ("withdrawal", None)


def test_is_spotify():
    assert sync.is_spotify({"description": "Spotify"})
    assert sync.is_spotify({"description": "SPOTIFY P1E6"})
    assert not sync.is_spotify({"description": "Сільпо"})
    # The card side of a jar transfer names the jar — it is not a charge.
    assert not sync.is_spotify({"description": "На банку «Spotify»", "mcc": 4829})


def test_parse_adjustment():
    assert parse_adjustment("+300 перевёл на карту") == (30000, "перевёл на карту")
    assert parse_adjustment("-50,5") == (-5050, "")
    assert parse_adjustment("−120 долг за 2023") == (-12000, "долг за 2023")
    assert parse_adjustment("300") == (30000, "")
    assert parse_adjustment("сто") is None
    assert parse_adjustment("0") is None


def test_parse_day_and_sender_key():
    assert parse_day("12.09.2022") == date(2022, 9, 12)
    assert parse_day("2022-09-12") is None
    assert len(sender_key("Дуже Довге Імʼя Відправника " * 5)) == 10


# ── database ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(sql.Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as s:
        await repo.set_state(s, repo.JAR, "jar")
        await repo.set_state(s, repo.CARD, "card")
        await repo.add_member(s, "Я", date(2022, 9, 1), is_owner=True)
        await s.commit()
    yield sessions
    await engine.dispose()


async def _get(s: AsyncSession, model, key):
    row = await s.get(model, key)
    assert row is not None
    return row


def _item(item_id: str, amount: int, description: str, day: date = date(2022, 10, 1), **extra) -> dict:
    return {"id": item_id, "time": _ts(day), "amount": amount, "description": description, "balance": 0, **extra}


@pytest.mark.asyncio
async def test_ingest_files_jar_items_and_learns_senders(db: async_sessionmaker[AsyncSession]):
    async with db() as s:
        result = await sync.ingest(
            s,
            "jar",
            [
                _item("a", 6000, "Від: Олександр Яковенко"),
                _item("b", 10000, "З чорної картки"),
                _item("c", -30000, "На чорну картку"),
            ],
        )
        assert [t.id for t in result.unknown] == ["a"] and not result.topups
        assert await repo.unknown_senders(s) == [("Олександр Яковенко", 1, 6000)]
        member = await repo.add_member(s, "Саша", date(2022, 9, 1), alias="Олександр Яковенко")
        assert (await _get(s, JarTransaction, "a")).member_id == member.id  # filed back
        owner = await repo.owner(s)
        assert owner is not None
        assert (await _get(s, JarTransaction, "b")).member_id == owner.id
        assert await repo.unknown_senders(s) == []

        again = await sync.ingest(
            s, "jar", [_item("a", 6000, "Від: Олександр Яковенко"), _item("d", 5000, "Від: Олександр Яковенко")]
        )
        assert [t.id for t in again.topups] == ["d"]  # "a" is not new
        await s.commit()


@pytest.mark.asyncio
async def test_ingest_card_keeps_only_spotify(db: async_sessionmaker[AsyncSession]):
    async with db() as s:
        result = await sync.ingest(
            s,
            "card",
            [
                _item("x", -36146, "Spotify", operationAmount=-799, currencyCode=840),
                _item("y", -12000, "Сільпо"),
            ],
        )
        assert [c.id for c in result.charges] == ["x"]
        charge = await _get(s, Charge, "x")
        assert (charge.amount, charge.operation_amount, charge.currency_code) == (36146, 799, 840)
        last = await repo.last_charge(s)
        assert last is not None and last.id == "x"
        assert await sync.ingest(s, "other", [_item("z", -1, "Spotify")]) == sync.Ingested()


@pytest.mark.asyncio
async def test_notices_are_claimed_once(db: async_sessionmaker[AsyncSession]):
    async with db() as s:
        assert await repo.claim_notice(s, 2, "before", "2026-11-12")
        assert not await repo.claim_notice(s, 2, "before", "2026-11-12")
        assert await repo.claim_notice(s, 3, "before", "2026-11-12")
        await repo.forget_notices(s, "before", "2026-11-12")
        assert await repo.claim_notice(s, 2, "before", "2026-11-12")


def test_migrations_match_the_models(tmp_path, monkeypatch):
    path = tmp_path / "migrated.db"
    monkeypatch.setattr(sql.settings, "database_url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(sql.alembic_config(), "head")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), sql.Base.metadata) == []
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_statement_skips_windows_before_the_account_existed(monkeypatch):
    from src.services.spotify import monobank

    calls = []

    async def window(account, start, end):
        calls.append(start)
        if len(calls) == 1:
            raise monobank.MonobankError('400 {"errorDescription":"Value field \'to\' out of bounds"}')
        return [{"id": f"i{start}", "time": start}]

    monkeypatch.setattr(monobank, "_window", window)
    items = await monobank.statement("jar", 0, 2 * monobank.WINDOW)
    assert [i["time"] for i in items] == [monobank.WINDOW]

    async def broken(account, start, end):
        raise monobank.MonobankError("500 down")

    monkeypatch.setattr(monobank, "_window", broken)
    with pytest.raises(monobank.MonobankError):
        await monobank.statement("jar", 0, 10)


@pytest.mark.asyncio
async def test_a_relinked_user_moves_to_a_lower_member_id(db: async_sessionmaker[AsyncSession]):
    async with db() as s, s.begin():
        low = await repo.add_member(s, "Низький", date(2022, 9, 1))
        high = await repo.add_member(s, "Високий", date(2022, 9, 1))
        high.tg_id = 777
    async with db() as s, s.begin():
        taken = await repo.member_by_tg(s, 777)
        target = await repo.member_by_invite(s, low.invite_code)
        assert taken is not None and target is not None
        taken.tg_id = None
        await s.flush()
        target.tg_id = 777
    async with db() as s:
        moved = await repo.member_by_tg(s, 777)
        assert moved is not None and moved.id == low.id


@pytest.mark.asyncio
async def test_monobank_webhook_route(monkeypatch):
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from src.interfaces.webhooks.routes import monobank as route

    monkeypatch.setattr(route.settings, "monobank_webhook_secret", "s3cret")
    assert (await route.monobank_check("s3cret")).status_code == 200
    with pytest.raises(HTTPException) as wrong:
        await route.monobank_check("wrong")
    assert wrong.value.status_code == 404
    # Never a non-200 for Monobank: it would switch the webhook off.
    request = MagicMock(json=AsyncMock(side_effect=ValueError("not json")))
    assert (await route.monobank_webhook("s3cret", request)).status_code == 200


def test_local_day_uses_the_timezone():
    moment = int(datetime(2026, 10, 11, 23, 30, tzinfo=UTC).timestamp())
    assert ledger.local_day(moment, TZ) == date(2026, 10, 12)


@pytest.mark.asyncio
async def test_bootstrap_sets_up_loads_history_and_adds_founders(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from src.interfaces.tg.notification import spotify_notification as notify
    from src.services.spotify import monobank

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'boot.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(sql.Base.metadata.create_all)
    monkeypatch.setattr(sql, "_engine", engine)
    monkeypatch.setattr(sql, "_sessions", async_sessionmaker(engine, expire_on_commit=False))
    for key, value in {
        "monobank_token": "t",
        "monobank_jar_id": "jar",
        "monobank_card_id": "card",
        "spotify_since": "2022-08-12",
        "telegram_admin_id": 1,
        "tz": "Europe/Berlin",
    }.items():
        monkeypatch.setattr(notify.settings, key, value, raising=False)
    info = {"accounts": [], "jars": [{"id": "jar", "title": "J", "currencyCode": 980, "balance": 0, "sendId": "jar/x"}]}
    monkeypatch.setattr(monobank, "client_info", AsyncMock(return_value=info))
    monkeypatch.setattr(monobank, "rate", AsyncMock(return_value=45.0))

    async def statement(account, start, end):
        if account == "jar":
            return [_item("a", 6000, "Від: Олена"), _item("b", 6000, "Від: Петро")]
        return [_item("x", -36146, "Spotify", operationAmount=-799, currencyCode=840, mcc=5815)]

    monkeypatch.setattr(monobank, "statement", statement)
    bot = MagicMock(send_message=AsyncMock())
    try:
        await notify.spotify_bootstrap(bot)
        async with sql.session() as s:
            names = sorted(m.name for m in await repo.members(s))
            assert names == ["Олена", "Петро", "Я"]
            assert await repo.get_state(s, repo.JAR_SEND) == "jar/x"
            assert (await repo.get_state(s, repo.HISTORY))["since"] == "2022-08-12"
        assert "готов" in bot.send_message.await_args.args[1]
        bot.send_message.reset_mock()
        await notify.spotify_bootstrap(bot)  # once only
        bot.send_message.assert_not_awaited()
    finally:
        await engine.dispose()
