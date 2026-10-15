"""When the next charge comes, how much it will be, and which reminders are due today.

Spotify bills on the same day every month (the day of the first payment), so the day is read
from the last charge instead of being configured. The amount is the last charge's price in
dollars at today's Monobank rate, with the card's markup measured on that last charge.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_DAY = 12
# Before the charge: three days ahead in the morning, the day before in the evening.
# After it: the charge itself sends the first notice, three days later — the second.
BEFORE_MORNING = 3
BEFORE_EVENING = 1
AFTER_DEBT = 3

MORNING = "morning"
EVENING = "evening"


def _on_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _next_month(day: date) -> tuple[int, int]:
    return (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)


def next_charge(today: date, last_charge: date | None, billing_day: int | None = None) -> date:
    """The day the next charge is expected; in the past while this month's one is late."""
    day = billing_day or (last_charge.day if last_charge else DEFAULT_DAY)
    if last_charge and (last_charge.year, last_charge.month) >= (today.year, today.month):
        return _on_day(*_next_month(today), day)
    return _on_day(today.year, today.month, day)


@dataclass(frozen=True)
class Forecast:
    day: date
    amount: int  # UAH kopecks
    price: int  # cents of the plan's currency
    rate: float  # UAH per unit used


def forecast(day: date, price: int, rate: float, markup: float = 1.0) -> Forecast:
    return Forecast(day=day, amount=round(price * rate * markup), price=price, rate=rate * markup)


def markup(amount: int, price: int, rate_then: float | None) -> float:
    """How much above the public rate the card converted the last charge (1.0 — unknown)."""
    if not rate_then or price <= 0:
        return 1.0
    return amount / price / rate_then


def due(today: date, slot: str, upcoming: date, last_charge: date | None) -> set[str]:
    """Which reminders this run should send: "before" (members + owner check) and/or "debt"."""
    actions: set[str] = set()
    if slot == MORNING and today == upcoming - timedelta(days=BEFORE_MORNING):
        actions.add("before")
    if slot == EVENING and today == upcoming - timedelta(days=BEFORE_EVENING):
        actions.add("before")
    if slot == MORNING and last_charge and today == last_charge + timedelta(days=AFTER_DEBT):
        actions.add("debt")
    return actions
