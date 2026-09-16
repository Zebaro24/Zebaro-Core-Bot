from src.interfaces.tg.formatters.job_stats import format_weekly_digest


def _stats(**overrides):
    base = {
        "period_days": 7,
        "totals": {"found": 10, "sent": 5, "review": 2, "rejected_by_filter": 3},
        "by_platform": [{"platform": "Djinni", "found": 10, "sent": 5, "applied": 1, "not_interested": 2}],
        "by_status": {"applied": 1, "not_interested": 2, "pending": 4},
        "response_rate": 0.5,
        "avg_hours_to_action": 12.345,
    }
    base.update(overrides)
    return base


def test_format_weekly_digest_includes_totals_and_status():
    text = format_weekly_digest(_stats())

    assert "Найдено: <b>10</b>" in text
    assert "🔥 Отправлено: <b>5</b>" in text
    assert "✅ Откликнулся: <b>1</b>" in text
    assert "Response rate: <b>50%</b>" in text
    assert "Среднее время реакции: <b>12.3 ч</b>" in text
    assert "Djinni" in text


def test_format_weekly_digest_omits_response_rate_when_none():
    text = format_weekly_digest(_stats(response_rate=None, avg_hours_to_action=None))

    assert "Response rate" not in text
    assert "Среднее время реакции" not in text


def test_format_weekly_digest_escapes_platform_name():
    text = format_weekly_digest(
        _stats(by_platform=[{"platform": "<script>", "found": 1, "sent": 1, "applied": 0, "not_interested": 0}])
    )

    assert "<script>" not in text
    assert "&lt;script&gt;" in text
