import pytest

from app.utils.format_memory import format_memory
from app.utils.format_time import format_duration


@pytest.mark.parametrize(
    "data,res",
    [
        (1024 * 1024, "1.00 MB"),
        (1024 * 1024 * 1024, "1.00 GB"),
        (1024**3 + (1024**2) * 20, "1.02 GB"),
    ],
)
def test_format_memory(data, res):
    assert format_memory(data) == res


@pytest.mark.parametrize(
    "seconds,res",
    [
        (0, None),
        (6, "6s"),
        (5 * 60 + 3, "5m 3s"),
        (5 * 60 * 60 + 5, "5h 0m"),
        (5 * 60 * 60 + 5 * 60, "5h 5m"),
        (5 * 60 * 60 * 24 + 8 * 60 * 60, "5d 8h"),
    ],
)
def test_format_duration(seconds, res):
    assert format_duration(seconds) == res
