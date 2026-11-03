"""The funnel by event time (GET /jobs/funnel?by=event): what happened in a period, from `history`.

The cohort is the events whose `occurred_at` (when it happened, not when it was written) falls in
[from, to). A change taken back is not a change: an event and its undo (`undo_of`) both drop out,
and so do the repeats it made on other copies (`cause`) — a test PATCH or the AI's mistake leaves
no trace in the numbers.

- `entered` — how many events led into each status;
- `transitions` — the moves, "from → to";
- `reached` — of the vacancies applied to in the period, how far each got by now;
- `rejections` — refusals by the stage they came at and the reason (`from` × `reason_code`);
- `time_to_reply` — hours from the application to the employer's first answer, both inside
  the history with real times: an `approximate` end and a `no_response` refusal (silence is no
  answer) are left out; the answer's time decides the period.
"""

from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings
from src.db.client import jobs_collection
from src.services.job_searcher.jobs_api import (
    SCOPE,
    STATUSES,
    Filters,
    group_keys,
    group_label,
    stage_rank,
    utc,
)

APPLIED = "applied"
ANSWERS = ("replied", "interview", "offer", "rejected_by_employer")
NO_RESPONSE = "no_response"
_RANK = {"applied": 1, "replied": 2, "interview": 3, "offer": 4}
_REACHED = ("applied", "replied", "interview", "offer")


def counted(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events that count, oldest first: without the undone ones, their undos and their repeats."""
    undone = {event["undo_of"] for event in history if event.get("undo_of")}
    kept = [
        event
        for event in history
        if not event.get("undo_of") and event.get("id") not in undone and event.get("cause") not in undone
    ]
    return sorted(
        (event for event in kept if isinstance(event.get("occurred_at"), datetime)), key=lambda e: e["occurred_at"]
    )


def percentile(values: list[float], share: float) -> float:
    """Linear interpolation between the closest ranks: p75 of [1, 2, 3, 4] is 3.25."""
    ordered = sorted(values)
    position = share * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def reply_hours(events: list[dict[str, Any]]) -> list[tuple[datetime, float]]:
    """(answer time, hours since the application) for each application that got an answer."""
    found: list[tuple[datetime, float]] = []
    applied_at: datetime | None = None
    for event in events:
        if event.get("to") == APPLIED:
            applied_at = None if event.get("approximate") else event["occurred_at"]
        elif event.get("to") in ANSWERS and applied_at is not None:
            if not event.get("approximate") and event.get("reason_code") != NO_RESPONSE:
                found.append((event["occurred_at"], (event["occurred_at"] - applied_at).total_seconds() / 3600))
            applied_at = None  # the first answer only
    return found


def _week(moment: datetime) -> str:
    year, week, _ = moment.replace(tzinfo=UTC).astimezone(ZoneInfo(settings.tz)).isocalendar()
    return f"{year}-W{week:02d}"


def _empty(key: str, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "events": 0,
        "entered": {status: 0 for status in STATUSES if status != "duplicate"},
        "transitions": Counter(),
        "applied": 0,
        "reached": dict.fromkeys(_REACHED, 0),
        "rejections": {},
        "_hours": [],
    }


class _Groups:
    def __init__(self, group_by: str) -> None:
        self.group_by = group_by
        self.groups: dict[str, dict[str, Any]] = {}

    def of(self, doc: dict[str, Any], moment: datetime) -> list[dict[str, Any]]:
        """The groups a fact about `doc` at `moment` counts in: by week, the moment's week."""
        keys = [_week(moment)] if self.group_by == "week" else group_keys(doc, self.group_by)
        return [self.groups.setdefault(key, _empty(key, group_label(key, self.group_by))) for key in keys]


def _count(groups: _Groups, doc: dict[str, Any], start: datetime, end: datetime) -> None:
    events = counted(doc.get("history") or [])
    for index, event in enumerate(events):
        moment = event["occurred_at"]
        if not start <= moment < end:
            continue
        frm, to = event.get("from") or "new", event.get("to") or "new"
        for group in groups.of(doc, moment):
            group["events"] += 1
            if to in group["entered"]:
                group["entered"][to] += 1
            group["transitions"][(frm, to)] += 1
            if to == "rejected_by_employer":
                by_stage = group["rejections"].setdefault(frm, {})
                code = event.get("reason_code") or "unknown"
                by_stage[code] = by_stage.get(code, 0) + 1
        if to == APPLIED:
            # How far this application got by now: every later event, inside the period or not.
            # A "no_response" refusal is silence, not an answer: it does not count as replied.
            ranks = (stage_rank(later.get("to") or "", later.get("reason_code")) for later in events[index:])
            rank = max(ranks, default=1)
            for group in groups.of(doc, moment):
                group["applied"] += 1
                for stage in _REACHED:
                    group["reached"][stage] += rank >= _RANK[stage]
    for answered_at, hours in reply_hours(events):
        if start <= answered_at < end and hours >= 0:
            for group in groups.of(doc, answered_at):
                group["_hours"].append(hours)


def _finish(group: dict[str, Any]) -> dict[str, Any]:
    hours = group.pop("_hours")
    reached = group["reached"]
    group["transitions"] = [
        {"from": frm, "to": to, "count": count} for (frm, to), count in group["transitions"].most_common()
    ]
    group["rejections"] = {stage: dict(Counter(codes).most_common()) for stage, codes in group["rejections"].items()}
    group["reply_rate"] = round(reached["replied"] / reached["applied"], 3) if reached["applied"] else None
    group["interview_rate"] = round(reached["interview"] / reached["applied"], 3) if reached["applied"] else None
    group["time_to_reply"] = {
        "count": len(hours),
        "median_hours": round(median(hours), 1) if hours else None,
        "p75_hours": round(percentile(hours, 0.75), 1) if hours else None,
    }
    return group


def event_groups(docs: list[dict[str, Any]], group_by: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    groups = _Groups(group_by)
    for doc in docs:
        _count(groups, doc, start, end)
    finished = [_finish(group) for group in groups.groups.values()]
    if group_by == "week":
        return sorted(finished, key=lambda group: group["key"])
    return sorted(finished, key=lambda group: (-group["events"], group["key"]))


async def event_funnel(filters: Filters, group_by: str) -> dict[str, Any]:
    # Any vacancy with an event since `from`: its later events tell how far an application got.
    query = filters.query(default_tiers=False, by_found=False)
    query["$and"].append({"history.occurred_at": {"$gte": filters.start}})
    docs = [doc async for doc in jobs_collection.find(query, {"description": 0})]
    groups = event_groups(docs, group_by, filters.start, filters.end)
    if not groups and group_by == "none":
        groups = [_finish(_empty("all", "all"))]
    return {
        "scope": SCOPE,
        "by": "event",
        "from": utc(filters.start),
        "to": utc(filters.end),
        "group_by": group_by,
        "groups": groups,
    }
