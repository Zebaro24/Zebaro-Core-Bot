"""MongoDB + SQLite → PostgreSQL, once, with every value checked (2026-11; removed with MongoDB).

    python scripts/migrate_to_pg.py --mongo mongodb://… --sqlite path/zebaro.db --pg postgresql+asyncpg://…
                                    [--replace]

1. Alembic brings PostgreSQL to head.
2. Every SQLite table is copied as is (sequences moved past the copied ids).
3. Every MongoDB document is mapped onto the new tables (src/services/job_searcher/models.py, the
   VPN tables, kv). A key the mapping does not know stops the run: nothing is dropped silently.
   Dropped on purpose, and only these: `jobs.date_utc` and `meta.jobs_repair` (the markers of the
   finished one-off repairs), `github_notification` (imported into github_repos already — checked).
4. Everything is read back and compared with the source: SQLite row for row, every MongoDB document
   rebuilt from its rows and compared value for value, types included. The one normalisation is
   MongoDB's own: a key holding null and a missing key are the same (`{f: None}` matches both); how
   many such nulls there were is printed.

All in one transaction: any mismatch rolls the whole copy back. The target must be empty unless
`--replace` (rehearsals): then the copied tables are emptied first. Exit 0 = copied and identical.
"""

import argparse
import asyncio
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from bson import Int64, ObjectId
from pymongo import MongoClient
from sqlalchemy import Table, create_engine, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402

import src.services.github.store  # noqa: E402 — every SQLite table on Base.metadata, as in env.py
import src.services.job_searcher.journal  # noqa: E402
import src.services.notify  # noqa: E402
import src.services.spotify.models  # noqa: E402,F401
from src.db import sql  # noqa: E402
from src.services.job_searcher.models import AiNoteMessage, JobEvent, JobRow, JobSync, ReviewSummary  # noqa: E402
from src.services.vpn.traffic import ClientState, TrafficDay  # noqa: E402

JOB_COLUMNS = {c.name for c in JobRow.__table__.columns} - {"id", "seen_before"}
SIMILAR = {"similar_to": "to", "similar_to_platform": "platform", "similar_seen_at": "seen_at",
           "similar_status": "status", "similar_clicked": "clicked"}  # fmt: skip
EVENT_RENAMED = {"from": "from_status", "to": "to_status"}
EVENT_COLUMNS = {c.name for c in JobEvent.__table__.columns} - {"job_id", "position"}
SYNC_COLUMNS = {c.name for c in JobSync.__table__.columns} - {"job_id"}
JOB_DROPPED = {"date_utc"}
KV_KEYS = ("search_window", "home_proxy_alert", "ai_notes:current")
VPN_CLIENT_COLUMNS = {c.name for c in ClientState.__table__.columns} - {"id"}
# Copied from SQLite in this order (foreign keys first).
SQLITE_SKIP = {"alembic_version"}
MONGO_COLLECTIONS = {"jobs", "meta", "vpn_clients", "vpn_traffic_daily", "github_notification"}


class Mismatch(Exception):
    pass


# ---- MongoDB → rows ------------------------------------------------------------------------


def _plain(value: Any, where: str) -> Any:
    """bson's Int64 is an int; an ObjectId anywhere but where the mapping expects it is a stop."""
    if isinstance(value, ObjectId):
        raise Mismatch(f"{where}: an ObjectId the mapping does not expect")
    if isinstance(value, Int64):
        return int(value)
    if isinstance(value, dict):
        return {k: _plain(v, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v, f"{where}[]") for v in value]
    return value


def job_rows(doc: dict[str, Any]) -> tuple[dict, list[dict], dict | None]:
    job_id = str(doc["_id"])
    where = f"jobs {job_id}"
    row: dict[str, Any] = {"id": job_id}
    similar: dict[str, Any] = {}
    events: list[dict] = []
    sync = None
    for key, value in doc.items():
        if key == "_id" or key in JOB_DROPPED:
            continue
        value = _plain(value, f"{where}.{key}")
        if key in SIMILAR:
            similar[SIMILAR[key]] = value
        elif key == "history":
            for position, event in enumerate(value or []):
                out = {"job_id": job_id, "position": position}
                for k, v in event.items():
                    name = EVENT_RENAMED.get(k, k)
                    if name not in EVENT_COLUMNS:
                        raise Mismatch(f"{where}.history[{position}]: unknown key {k!r}")
                    out[name] = v
                events.append(out)
        elif key == "tg_sync":
            unknown = set(value) - SYNC_COLUMNS
            if unknown:
                raise Mismatch(f"{where}.tg_sync: unknown keys {sorted(unknown)}")
            sync = {"job_id": job_id, **value}
        elif key in JOB_COLUMNS:
            row[key] = value
        else:
            raise Mismatch(f"{where}: unknown key {key!r}")
    row["seen_before"] = similar or None
    return row, events, sync


def job_doc(row: dict, events: list[dict], sync: dict | None) -> dict[str, Any]:
    """The MongoDB document back from its rows — what the comparison checks."""
    doc: dict[str, Any] = {"_id": row["id"]}
    for key, value in row.items():
        if key not in ("id", "seen_before"):
            doc[key] = value
    for old, new in SIMILAR.items():
        if row["seen_before"] and new in row["seen_before"]:
            doc[old] = row["seen_before"][new]
    if events:
        doc["history"] = [
            {
                ({v: k for k, v in EVENT_RENAMED.items()}).get(k, k): v
                for k, v in e.items()
                if k not in ("job_id", "position")
            }
            for e in sorted(events, key=lambda e: e["position"])
        ]
    if sync:
        doc["tg_sync"] = {k: v for k, v in sync.items() if k != "job_id"}
    return doc


# ---- comparison ----------------------------------------------------------------------------


def _strip_nulls(value: Any, nulls: Counter, path: str) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if v is None:
                nulls[f"{path}.{k}" if path else k] += 1
                continue
            out[k] = _strip_nulls(v, nulls, f"{path}.{k}" if path else k)
        return out
    if isinstance(value, list):
        return [_strip_nulls(v, nulls, f"{path}[]") for v in value]
    return value


def same(a: Any, b: Any, where: str) -> None:
    """Equal values of the same type: True is not 1, 1.0 is not 1, a datetime to the microsecond."""
    if type(a) is not type(b):
        raise Mismatch(f"{where}: {type(a).__name__} {a!r} ≠ {type(b).__name__} {b!r}")
    if isinstance(a, dict):
        if a.keys() != b.keys():
            raise Mismatch(f"{where}: keys {sorted(a.keys() ^ b.keys())} differ")
        for k in a:
            same(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            raise Mismatch(f"{where}: {len(a)} items ≠ {len(b)}")
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            same(x, y, f"{where}[{i}]")
    elif a != b:
        raise Mismatch(f"{where}: {a!r} ≠ {b!r}")


def source_doc(doc: dict[str, Any], dropped: set[str]) -> dict[str, Any]:
    out = {k: _plain(v, "source") if k != "_id" else str(v) for k, v in doc.items() if k not in dropped}
    return out


# ---- the run -------------------------------------------------------------------------------


async def _rows(conn: AsyncConnection, table: Table, order: Any = None) -> list[dict]:
    query = select(table)
    if order is not None:
        query = query.order_by(*order)
    return [dict(r._mapping) for r in (await conn.execute(query)).all()]


async def copy_sqlite(conn: AsyncConnection, path: Path, report: list[str]) -> None:
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    if src.execute("pragma integrity_check").fetchone()[0] != "ok":
        raise Mismatch("SQLite: integrity_check failed")
    version = src.execute("select version_num from alembic_version").fetchone()[0]
    typed = create_engine(f"sqlite:///file:{path.as_posix()}?mode=ro&uri=true")
    target = sql.Base.metadata
    present = {r[0] for r in src.execute("select name from sqlite_master where type='table'")}
    unknown = present - SQLITE_SKIP - set(target.tables) - {n for n in present if n.startswith("sqlite_")}
    if unknown:
        raise Mismatch(f"SQLite tables no model knows: {sorted(unknown)} — they would be left behind")
    for table in target.sorted_tables:
        exists = src.execute("select 1 from sqlite_master where type='table' and name=?", (table.name,)).fetchone()
        if not exists:
            continue
        source_cols = [r[1] for r in src.execute(f'pragma table_info("{table.name}")')]
        if set(source_cols) != {c.name for c in table.columns}:
            raise Mismatch(f"SQLite {table.name}: columns {source_cols} ≠ the model's")
        # Read through the model's types (dates, booleans, JSON), the way the bot read them.
        with typed.connect() as source_conn:
            rows = [dict(r._mapping) for r in source_conn.execute(select(table))]
            raw_count = source_conn.execute(select(func.count()).select_from(table)).scalar()
        if raw_count != len(rows):
            raise Mismatch(f"SQLite {table.name}: {raw_count} rows, {len(rows)} read")
        if rows:
            await conn.execute(insert(table), rows)
        back = await _rows(conn, table)
        key = [c.name for c in table.primary_key.columns]

        def by_key(rs: list[dict], key: list[str] = key) -> dict:
            return {tuple(r[k] for k in key): r for r in rs}

        source, copied = by_key(rows), by_key(back)
        if source.keys() != copied.keys():
            raise Mismatch(f"SQLite {table.name}: keys differ")
        for k, r in source.items():
            same(copied[k], r, f"SQLite {table.name} {k}")
        # An autoincrement id copied explicitly leaves its sequence at 1: move it past the rows.
        for col in table.primary_key.columns:
            if col.autoincrement is True or (
                col.autoincrement == "auto" and col.type.python_type is int and len(key) == 1
            ):
                top = (await conn.execute(select(func.max(col)))).scalar() or 0
                await conn.execute(
                    text("select setval(pg_get_serial_sequence(:t, :c), :n, false)"),
                    {"t": table.name, "c": col.name, "n": top + 1},
                )
        report.append(f"  sqlite {table.name:28} {len(rows):5} = {len(back):5}")
    report.append(f"  (SQLite schema was at {version})")


async def copy_mongo(conn: AsyncConnection, mongo: Any, report: list[str], nulls: Counter) -> None:
    jobs_t, events_t, sync_t = JobRow.__table__, JobEvent.__table__, JobSync.__table__
    docs = list(mongo["jobs"].find().sort("_id", 1))
    rows, events, syncs = [], [], []
    for doc in docs:
        row, ev, sync = job_rows(doc)
        rows.append(row)
        events += ev
        if sync:
            syncs.append(sync)
    # group_id points at jobs: parents before children is not guaranteed, so the key is set after.
    groups = {r["id"]: r.pop("group_id", None) for r in rows}
    full = [{c: r.get(c) for c in [c.name for c in jobs_t.columns]} for r in rows]
    for r in full:
        r["group_id"] = None
    if full:
        await conn.execute(insert(jobs_t), full)
    for job_id, group in groups.items():
        if group is not None:
            await conn.execute(jobs_t.update().where(jobs_t.c.id == job_id).values(group_id=group))
    if events:
        await conn.execute(insert(events_t), [{c.name: e.get(c.name) for c in events_t.columns} for e in events])
    if syncs:
        await conn.execute(insert(sync_t), [{c.name: s.get(c.name) for c in sync_t.columns} for s in syncs])

    back_rows = {r["id"]: r for r in await _rows(conn, jobs_t)}
    back_events: dict[str, list[dict]] = {}
    for e in await _rows(conn, events_t):
        back_events.setdefault(e["job_id"], []).append(e)
    back_sync = {s["job_id"]: s for s in await _rows(conn, sync_t)}
    if len(back_rows) != len(docs):
        raise Mismatch(f"jobs: {len(docs)} documents ≠ {len(back_rows)} rows")
    for doc in docs:
        job_id = str(doc["_id"])
        rebuilt = job_doc(back_rows[job_id], back_events.get(job_id, []), back_sync.get(job_id))
        same(
            _strip_nulls(rebuilt, Counter(), ""),
            _strip_nulls(source_doc(doc, JOB_DROPPED), nulls, "jobs"),
            f"jobs {job_id}",
        )
    copied_events = sum(map(len, back_events.values()))
    report.append(
        f"  mongo  jobs                         {len(docs):5} = {len(back_rows):5}"
        f"  (events {len(events)} = {copied_events}, outbox {len(syncs)} = {len(back_sync)})"
    )

    # meta → kv / review_summaries / ai_note_messages
    kv_t, rs_t, ai_t = sql.Kv.__table__, ReviewSummary.__table__, AiNoteMessage.__table__
    meta = list(mongo["meta"].find())
    kv, rs, ai, dropped = [], [], [], []
    for doc in meta:
        key = doc["_id"]
        body = {k: v for k, v in doc.items() if k != "_id"}
        if key == "jobs_repair":
            dropped.append(key)
        elif key in KV_KEYS:
            kv.append({"key": key, "value": _plain(body, f"meta {key}")})
        elif key.startswith("review_summary:"):
            if set(body) != {"parts"}:
                raise Mismatch(f"meta {key}: keys {sorted(body)}")
            rs.append({"day": key.split(":", 1)[1], "parts": _plain(body["parts"], f"meta {key}")})
        elif key.startswith("ai_notes:") and key.split(":", 1)[1].isdigit():
            if set(body) != {"chat_id", "entries"}:
                raise Mismatch(f"meta {key}: keys {sorted(body)}")
            ai.append({"message_id": int(key.split(":", 1)[1]), "chat_id": int(body["chat_id"]),
                       "entries": _plain(body["entries"], f"meta {key}")})  # fmt: skip
        else:
            raise Mismatch(f"meta {key!r}: no place for it")
    for table, items in ((kv_t, kv), (rs_t, rs), (ai_t, ai)):
        if items:
            await conn.execute(insert(table), items)
    back = {r["key"]: r["value"] for r in await _rows(conn, kv_t)}
    back.update({f"review_summary:{r['day']}": {"parts": r["parts"]} for r in await _rows(conn, rs_t)})
    back.update(
        {
            f"ai_notes:{r['message_id']}": {"chat_id": r["chat_id"], "entries": r["entries"]}
            for r in await _rows(conn, ai_t)
        }
    )
    for doc in meta:
        if doc["_id"] in dropped:
            continue
        same(back[doc["_id"]], {k: _plain(v, "meta") for k, v in doc.items() if k != "_id"}, f"meta {doc['_id']}")
    report.append(f"  mongo  meta                         {len(meta):5} = {len(back):5} + dropped {dropped}"
                  f"  (kv {len(kv)}, review_summaries {len(rs)}, ai_note_messages {len(ai)})")  # fmt: skip

    # vpn
    vc_t, vd_t = ClientState.__table__, TrafficDay.__table__
    clients = list(mongo["vpn_clients"].find())
    for doc in clients:
        unknown = set(doc) - VPN_CLIENT_COLUMNS - {"_id"}
        if unknown:
            raise Mismatch(f"vpn_clients {doc['_id']}: unknown keys {sorted(unknown)}")
    if clients:
        await conn.execute(
            insert(vc_t),
            [{"id": d["_id"], **{c: _plain(d.get(c), "vpn") for c in VPN_CLIENT_COLUMNS}} for d in clients],
        )
    back_c = {r["id"]: r for r in await _rows(conn, vc_t)}
    for doc in clients:
        rebuilt = {"_id": back_c[doc["_id"]]["id"], **{k: v for k, v in back_c[doc["_id"]].items() if k != "id"}}
        same(
            _strip_nulls(rebuilt, Counter(), ""),
            _strip_nulls(source_doc(doc, set()) | {"_id": doc["_id"]}, nulls, "vpn_clients"),
            f"vpn_clients {doc['_id']}",
        )
    days = list(mongo["vpn_traffic_daily"].find())
    for doc in days:
        if set(doc) != {"_id", "client_id", "day", "rx", "tx"} or doc["_id"] != f"{doc['client_id']}:{doc['day']}":
            raise Mismatch(f"vpn_traffic_daily {doc['_id']}: unexpected shape")
    if days:
        await conn.execute(
            insert(vd_t), [{k: _plain(d[k], "vpn") for k in ("client_id", "day", "rx", "tx")} for d in days]
        )
    back_d = {(r["client_id"], r["day"]): r for r in await _rows(conn, vd_t)}
    for doc in days:
        r = back_d[(doc["client_id"], doc["day"])]
        same(
            {k: r[k] for k in ("client_id", "day", "rx", "tx")},
            {k: _plain(doc[k], "vpn") for k in ("client_id", "day", "rx", "tx")},
            f"vpn day {doc['_id']}",
        )
    report.append(f"  mongo  vpn_clients                  {len(clients):5} = {len(back_c):5}")
    report.append(f"  mongo  vpn_traffic_daily            {len(days):5} = {len(back_d):5}")


async def check_github_imported(conn: AsyncConnection, mongo: Any, report: list[str]) -> None:
    legacy = list(mongo["github_notification"].find())
    rows = (await conn.execute(text(
        "select r.full_name, t.chat_id, t.thread_id from github_repos r join github_topics t on t.id = r.topic_id"
    ))).all()  # fmt: skip
    have = {(name, int(chat), int(thread)) for name, chat, thread in rows}
    for doc in legacy:
        if (doc["full_repo_name"], int(doc["tg_chat_id"]), int(doc["thread_id"])) not in have:
            raise Mismatch(f"github_notification {doc['full_repo_name']}: not in github_repos — would be lost")
    report.append(f"  mongo  github_notification          {len(legacy):5} — all in github_repos, not copied")


async def run(args: argparse.Namespace) -> int:
    sql.settings.database_url = args.pg
    await asyncio.to_thread(command.upgrade, sql.alembic_config(), "head")
    mongo = MongoClient(args.mongo, tz_aware=False).get_database()
    engine = create_async_engine(args.pg)
    report: list[str] = []
    nulls: Counter = Counter()
    try:
        async with engine.begin() as conn:
            tables = list(sql.Base.metadata.sorted_tables)
            counts = {t.name: (await conn.execute(select(func.count()).select_from(t))).scalar() for t in tables}
            if any(counts.values()):
                if not args.replace:
                    raise Mismatch(
                        f"PostgreSQL is not empty: { {k: v for k, v in counts.items() if v} } (--replace to empty it)"
                    )
                for table in reversed(tables):  # children first; the sequences are set again after the copy
                    await conn.execute(table.delete())
            extra = {n for n in mongo.list_collection_names() if not n.startswith("system.")} - MONGO_COLLECTIONS
            if extra:
                raise Mismatch(f"MongoDB collections the mapping does not know: {sorted(extra)}")
            await copy_sqlite(conn, Path(args.sqlite), report)
            await check_github_imported(conn, mongo, report)
            await copy_mongo(conn, mongo, report, nulls)
            # None is SQL NULL: a JSON `null` stored anywhere would answer IS NULL wrongly.
            for table in tables:
                for col in table.columns:
                    if isinstance(col.type, sql.Json):
                        n = (await conn.execute(select(func.count()).where(col == text("'null'::jsonb")))).scalar()
                        if n:
                            raise Mismatch(f"{table.name}.{col.name}: {n} JSON nulls instead of SQL NULL")
    except Mismatch as e:
        print(f"STOP, nothing written: {e}")
        return 1
    finally:
        await engine.dispose()
    print("Copied and identical:")
    print("\n".join(report))
    print("MongoDB nulls kept as SQL NULL (a null and a missing key are one thing there):")
    for path, n in sorted(nulls.items()):
        print(f"  {path:40} {n}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mongo", required=True)
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--pg", required=True)
    parser.add_argument("--replace", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
