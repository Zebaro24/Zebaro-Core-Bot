from datetime import datetime
from unittest.mock import patch

import pytest

from src.services.job_searcher.listeners.base import resolve_year


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 15)


@pytest.mark.parametrize(
    "month,expected_year",
    [
        (3, 2026),  # тот же месяц, что и сейчас
        (2, 2026),  # прошедший месяц этого года
        (1, 2026),  # прошедший месяц этого года
        (4, 2025),  # на 1 месяц вперёд — не может быть будущим, значит прошлый год
        (12, 2025),  # декабрь при "сейчас" в марте — прошлый год
    ],
)
def test_resolve_year_never_returns_future_date(month, expected_year):
    with patch("src.services.job_searcher.listeners.base.datetime", _FixedDatetime):
        assert resolve_year(month) == expected_year
