from src.interfaces.tg.formatters.job_stats import format_weekly_digest, format_weekly_digest_rich


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


def test_rich_digest_uses_tables_and_explains_rejections():
    text = format_weekly_digest_rich(_stats(by_reason={"senior": 12, "no stack match": 3}))

    assert text.startswith("<h2>📊 Вакансии за 7 дней</h2>")
    assert "<th>🔥 Твой стек</th>" in text
    assert '<td align="center">10</td>' in text
    assert "<li>✅ Откликнулся — <b>1</b></li>" in text
    assert "<p>Откликаешься на <b>50%</b> присланного, реагируешь в среднем за <b>12.3 ч</b></p>" in text
    assert "<tr><td>Djinni</td>" in text
    assert "<li>senior — <b>12</b></li><li>стек не совпал — <b>3</b></li>" in text


def test_rich_digest_escapes_platform_and_skips_empty_sections():
    text = format_weekly_digest_rich(
        _stats(
            by_platform=[{"platform": "<script>", "found": 1, "sent": 1, "applied": 0, "not_interested": 0}],
            response_rate=None,
            avg_hours_to_action=None,
        )
    )

    assert "&lt;script&gt;" in text
    assert "Откликаешься" not in text
    assert "Почему не прислал" not in text
