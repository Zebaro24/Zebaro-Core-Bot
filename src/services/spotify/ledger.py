"""Who paid what and who owes what — pure functions over the stored rows.

Nothing is accumulated anywhere: every balance is recomputed from the whole history, so a
corrected join date or a reassigned top-up fixes every number at once.

* a charge is split equally among the members active on its day; the kopecks that do not
  divide go to the owner (or, without the owner, to the earliest member);
* paid = the member's jar top-ups + adjustments; balance = paid − shares.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo

from src.services.spotify.models import Adjustment, Charge, JarTransaction, Member

MAX_MEMBERS = 6  # Spotify Premium Family


def local_day(timestamp: int, tz: tzinfo) -> date:
    return datetime.fromtimestamp(timestamp, tz).date()


def split(amount: int, members: list[Member]) -> dict[int, int]:
    """Kopecks of one charge per member id; the remainder goes to the owner."""
    if not members:
        return {}
    ordered = sorted(members, key=lambda m: (not m.is_owner, m.id))
    base, remainder = divmod(amount, len(ordered))
    shares = {m.id: base for m in ordered}
    shares[ordered[0].id] += remainder
    return shares


@dataclass
class Account:
    member: Member
    topups: int = 0
    adjustments: int = 0
    owed: int = 0
    charges: int = 0  # how many charges the member had a share in

    @property
    def paid(self) -> int:
        return self.topups + self.adjustments

    @property
    def balance(self) -> int:
        return self.paid - self.owed


@dataclass
class Ledger:
    accounts: dict[int, Account] = field(default_factory=dict)
    total_charged: int = 0
    unshared: int = 0  # charges made on a day nobody was active: nobody to bill

    def __getitem__(self, member_id: int) -> Account:
        return self.accounts[member_id]


def counted(transaction: JarTransaction) -> bool:
    """A jar movement that is someone's payment."""
    return transaction.member_id is not None and not transaction.ignored and transaction.kind in ("topup", "own")


def build(
    members: Iterable[Member],
    charges: Iterable[Charge],
    transactions: Iterable[JarTransaction],
    adjustments: Iterable[Adjustment],
    tz: tzinfo,
) -> Ledger:
    members = list(members)
    ledger = Ledger(accounts={m.id: Account(m) for m in members})
    for charge in charges:
        ledger.total_charged += charge.amount
        day = local_day(charge.time, tz)
        shares = split(charge.amount, [m for m in members if m.active_on(day)])
        if not shares:
            ledger.unshared += charge.amount
        for member_id, share in shares.items():
            ledger.accounts[member_id].owed += share
            ledger.accounts[member_id].charges += 1
    for transaction in transactions:
        if counted(transaction) and transaction.member_id in ledger.accounts:
            ledger.accounts[transaction.member_id].topups += transaction.amount
    for adjustment in adjustments:
        if adjustment.member_id in ledger.accounts:
            ledger.accounts[adjustment.member_id].adjustments += adjustment.amount
    return ledger


def months_covered(balance: int, share: int) -> int:
    """How many future charges the balance already pays for (0 when in debt)."""
    if share <= 0 or balance <= 0:
        return 0
    return balance // share


def to_pay(balance: int, share: int) -> int:
    """What a member should put in before the next charge so the balance stays ≥ 0."""
    return max(0, share - balance)
