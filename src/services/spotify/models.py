"""Tables of the Spotify family subscription. Money is in kopecks (cents for a foreign
currency), time is a Unix timestamp as Monobank gives it: both stay exact and portable
between SQLite and Postgres.
"""

from datetime import date

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.sql import Base


class Member(Base):
    """A person in the family plan; the owner is one of them and pays a share too."""

    __tablename__ = "spotify_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    is_owner: Mapped[bool] = mapped_column(default=False)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)
    invite_code: Mapped[str] = mapped_column(String(32), unique=True)
    # Shares of the charges made from joined_on up to (not including) left_on.
    joined_on: Mapped[date]
    left_on: Mapped[date | None] = mapped_column(default=None)
    notify: Mapped[bool] = mapped_column(default=True)

    aliases: Mapped[list["Alias"]] = relationship(
        back_populates="member", cascade="all, delete-orphan", lazy="selectin"
    )

    def active_on(self, day: date) -> bool:
        return self.joined_on <= day and (self.left_on is None or day < self.left_on)


class Alias(Base):
    """A sender name as Monobank shows it ("Від: <name>") and whose money it is.

    No member — the owner said "not ours": that sender's top-ups are left out for good.
    """

    __tablename__ = "spotify_aliases"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("spotify_members.id", ondelete="CASCADE"))

    member: Mapped[Member | None] = relationship(back_populates="aliases")


class JarTransaction(Base):
    """A movement of the jar. Only kind "topup" with a member counts as someone's payment."""

    __tablename__ = "spotify_jar_transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Monobank's id
    time: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    balance: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(String(256), default="")
    comment: Mapped[str] = mapped_column(String(512), default="")
    # "topup" — from someone ("Від: …"), "own" — the owner's own top-up, "withdrawal" — taken out.
    kind: Mapped[str] = mapped_column(String(16))
    sender: Mapped[str | None] = mapped_column(String(128), default=None)
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("spotify_members.id", ondelete="SET NULL"), index=True, default=None
    )
    # The owner left this one transaction out (a mistake, a refund).
    ignored: Mapped[bool] = mapped_column(default=False)


class Charge(Base):
    """A Spotify payment from the card: the cost split among the members active that day."""

    __tablename__ = "spotify_charges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    time: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(BigInteger)  # UAH kopecks paid; a refund is negative
    operation_amount: Mapped[int] = mapped_column(BigInteger)  # in the plan's currency (cents)
    currency_code: Mapped[int] = mapped_column(default=840)
    # Monobank's public rate when the bot saw the charge live: measures the card's markup.
    rate: Mapped[float | None] = mapped_column(default=None)


class Adjustment(Base):
    """A correction by hand: money that went past the jar, a debt written off."""

    __tablename__ = "spotify_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("spotify_members.id", ondelete="CASCADE"), index=True)
    time: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(BigInteger)  # + counts as paid, − as owed
    note: Mapped[str] = mapped_column(String(256), default="")


class Notice(Base):
    """A reminder already sent: a restart or a second run the same day sends nothing twice."""

    __tablename__ = "spotify_notices"

    member_id: Mapped[int] = mapped_column(primary_key=True)  # 0 — the owner's report
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    period: Mapped[str] = mapped_column(String(32), primary_key=True)


class State(Base):
    """Small settings and cursors: the jar and the card in use, the last poll."""

    __tablename__ = "spotify_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
