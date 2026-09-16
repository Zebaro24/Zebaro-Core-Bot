import html
from typing import Any


def format_weekly_digest(stats: dict[str, Any]) -> str:
    totals = stats["totals"]
    by_status = stats["by_status"]

    text = f"<b>📊 Джоб-дайджест за {stats['period_days']} дней</b>\n\n"
    text += (
        f"Найдено: <b>{totals['found']}</b>\n"
        f"🔥 Отправлено: <b>{totals['sent']}</b>\n"
        f"❓ На проверку: <b>{totals['review']}</b>\n"
        f"Отфильтровано: <b>{totals['rejected_by_filter']}</b>\n\n"
        f"✅ Откликнулся: <b>{by_status['applied']}</b>\n"
        f"❌ Не интересует: <b>{by_status['not_interested']}</b>\n"
        f"⏳ Без реакции: <b>{by_status['pending']}</b>\n"
    )

    response_rate = stats["response_rate"]
    if response_rate is not None:
        text += f"\nResponse rate: <b>{response_rate:.0%}</b>"

    avg_hours = stats["avg_hours_to_action"]
    if avg_hours is not None:
        text += f"\nСреднее время реакции: <b>{avg_hours:.1f} ч</b>"

    by_platform = stats["by_platform"]
    if by_platform:
        text += "\n\n<b>По площадкам:</b>\n"
        for platform_stats in by_platform:
            text += (
                f"• {html.escape(platform_stats['platform'])}: "
                f"найдено {platform_stats['found']}, "
                f"отправлено {platform_stats['sent']}, "
                f"откликнулся {platform_stats['applied']}\n"
            )

    return text
