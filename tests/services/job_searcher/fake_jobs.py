"""An in-memory jobs collection for the Jobs API tests.

CI has no MongoDB. The fake knows only the operators the bot uses and fails loudly on any other,
so a query it accepts means the same here and in the database. $regex runs through Python's `re`:
words.py writes its patterns so that the two engines agree. Dotted keys ("tg_sync.state",
"history.cause") reach into sub-documents and arrays the way MongoDB does.
"""

import copy
import re
from typing import Any

_MISSING = object()


def _values(doc: dict[str, Any], key: str) -> list[Any]:
    """What a (dotted) key points at; through an array, every element's value."""
    current: list[Any] = [doc]
    parts = key.split(".")
    for index, part in enumerate(parts):
        found: list[Any] = []
        for item in current:
            value = item.get(part, _MISSING) if isinstance(item, dict) else _MISSING
            if isinstance(value, list) and index < len(parts) - 1:
                found.extend(value)
            else:
                found.append(None if value is _MISSING else value)
        current = found
    return current


def _equal(value: Any, target: Any) -> bool:
    if isinstance(target, re.Pattern):
        return isinstance(value, str) and target.search(value) is not None
    if target is None:
        return value is None  # MongoDB: null matches a missing field too
    return bool(value == target)


def _match_value(value: Any, condition: Any) -> bool:
    if not (isinstance(condition, dict) and condition and all(key.startswith("$") for key in condition)):
        return _equal(value, condition)
    for op, arg in condition.items():
        if op == "$in":
            ok = any(_equal(value, item) for item in arg)
        elif op == "$ne":
            ok = not _equal(value, arg)
        elif op == "$gte":
            ok = value is not None and value >= arg
        elif op == "$lt":
            ok = value is not None and value < arg
        elif op == "$lte":
            ok = value is not None and value <= arg
        elif op == "$regex":
            ok = isinstance(value, str) and re.search(arg, value) is not None
        else:
            raise NotImplementedError(op)
        if not ok:
            return False
    return True


def matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, condition in query.items():
        if key == "$and":
            ok = all(matches(doc, part) for part in condition)
        elif key == "$or":
            ok = any(matches(doc, part) for part in condition)
        elif key == "$nor":
            ok = not any(matches(doc, part) for part in condition)
        elif key.startswith("$"):
            raise NotImplementedError(key)
        elif "." in key:
            ok = any(_match_value(value, condition) for value in _values(doc, key))
        else:
            ok = _match_value(doc.get(key), condition)
        if not ok:
            return False
    return True


def _project(doc: dict[str, Any], projection: dict[str, int] | None) -> dict[str, Any]:
    if not projection:
        return copy.deepcopy(doc)
    if all(flag == 0 for flag in projection.values()):
        return {key: copy.deepcopy(value) for key, value in doc.items() if key not in projection}
    return {key: copy.deepcopy(value) for key, value in doc.items() if projection.get(key) or key == "_id"}


def _apply(doc: dict[str, Any], update: dict[str, Any]) -> None:
    for op, fields in update.items():
        if op not in ("$set", "$push"):
            raise NotImplementedError(op)
        for key, value in fields.items():
            *path, last = key.split(".")
            target = doc
            for part in path:
                target = target.setdefault(part, {})
            if op == "$set":
                target[last] = copy.deepcopy(value)
            else:
                target.setdefault(last, []).append(copy.deepcopy(value))


class FakeCursor:
    """Sorts and limits the stored documents; the projection is applied on the way out, as in MongoDB."""

    def __init__(self, docs: list[dict[str, Any]], projection: dict[str, int] | None = None) -> None:
        self._docs = docs
        self._projection = projection

    def sort(self, keys: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(keys):

            def value(doc: dict[str, Any], key: str = key) -> Any:
                return _values(doc, key)[0]

            self._docs.sort(key=value, reverse=direction < 0)
        return self

    def limit(self, count: int) -> "FakeCursor":
        self._docs = self._docs[:count]
        return self

    def __aiter__(self) -> "FakeCursor":
        self._iter = iter([_project(doc, self._projection) for doc in self._docs])
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


class _Result:
    def __init__(self, modified: int) -> None:
        self.modified_count = modified


class FakeJobs:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = list(docs or [])

    def find(self, query: dict[str, Any], projection: dict[str, int] | None = None) -> FakeCursor:
        return FakeCursor([doc for doc in self.docs if matches(doc, query)], projection)

    async def find_one(self, query: dict[str, Any], projection: dict[str, int] | None = None) -> dict[str, Any] | None:
        return next((_project(doc, projection) for doc in self.docs if matches(doc, query)), None)

    async def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], return_document: Any = None
    ) -> dict[str, Any] | None:
        doc = next((doc for doc in self.docs if matches(doc, query)), None)
        if doc is None:
            return None
        before = copy.deepcopy(doc)
        _apply(doc, update)
        return copy.deepcopy(doc) if return_document else before

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> _Result:
        doc = next((doc for doc in self.docs if matches(doc, query)), None)
        if doc is None and upsert:
            doc = {key: value for key, value in query.items() if not key.startswith("$")}
            self.docs.append(doc)
        if doc is not None:
            _apply(doc, update)
        return _Result(int(doc is not None))

    async def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> _Result:
        found = [doc for doc in self.docs if matches(doc, query)]
        for doc in found:
            _apply(doc, update)
        return _Result(len(found))

    def by_id(self, object_id: Any) -> dict[str, Any]:
        return next(doc for doc in self.docs if doc["_id"] == object_id)
