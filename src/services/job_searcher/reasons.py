"""Reason codes of a status: one dictionary per public status that takes a reason.

The owner's two "no"s keep the codes of their Telegram buttons; the employer's refusal reuses
the same words where the meaning is the same (experience, stack, location, english), so "I do not
pass" and "they turned me down" can be compared. A new code is an edit here and a deploy: until
then a client sends `other` with a `suggested_code`.

The descriptions are read by the model that picks a code (GET /jobs/reasons), hence Russian and
specific.
"""

OTHER = "other"
MUTED = "muted"  # "never send this company again": a Telegram button only (dedup.py acts on it)

REASONS: dict[str, dict[str, str]] = {
    "rejected_by_employer": {
        "no_response": "Отклик остался без ответа. Ставит бот сам после долгой тишины",
        "no_reason": "Отказ без причины: шаблонное «выбрали другого кандидата», «не готовы двигаться дальше»",
        "position_closed": "Вакансия закрыта, заморожена или уже занята",
        "experience": "Не хватает опыта или уровня (нужен middle/senior, больше лет)",
        "stack": "Не тот стек или не хватает конкретной технологии",
        "location": "Не подходит страна, город, часовой пояс или нужен офис",
        "work_permit": "Нет разрешения на работу, визы или нужного гражданства",
        "english": "Не хватает английского (или другого языка)",
        "salary": "Не сошлись по зарплате или условиям оплаты",
        OTHER: "Ни один код не подходит: обязательно suggested_code и reason",
    },
    "mismatch": {
        "experience": "Владелец не проходит по опыту или уровню",
        "location": "Офис, страна или релокация, которые владельцу не подходят",
        "english": "Требуемый английский выше уровня владельца",
        "stack": "Владелец не знает нужный стек",
        OTHER: "Другая причина: обязательно suggested_code и reason",
    },
    "not_interested": {
        "role": "Не та роль",
        "stack": "Стек не интересен",
        "domain": "Не интересны домен или компания",
        "conditions": "Не устраивают условия",
        OTHER: "Просто нет: обязательно suggested_code и reason",
        MUTED: "Компанию больше не присылать (только кнопкой в Telegram)",
    },
}
# Codes a client may not set: their effect lives in the bot.
BUTTON_ONLY = {MUTED}

# Short words for a Telegram status line: "Отказ: зарплата".
EMPLOYER_LABELS = {
    "no_response": "нет ответа",
    "no_reason": "без причины",
    "position_closed": "вакансия закрыта",
    "experience": "опыт / уровень",
    "stack": "стек",
    "location": "локация",
    "work_permit": "разрешение на работу",
    "english": "английский",
    "salary": "зарплата",
    OTHER: "другое",
}


def public_reasons() -> dict[str, list[dict[str, str]]]:
    """GET /jobs/reasons: the codes a client may set, per status."""
    return {
        status: [{"code": code, "description": text} for code, text in codes.items() if code not in BUTTON_ONLY]
        for status, codes in REASONS.items()
    }
