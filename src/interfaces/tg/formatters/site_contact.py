import html

from src.services.site_contact import SiteContact

_FLAGS = {"en": "🇬🇧", "uk": "🇺🇦"}


def site_contact_to_html(contact: SiteContact) -> str:
    """Everything the visitor typed is escaped: the form is a public input."""
    return (
        f"📨 <b>Сообщение с zebaro.dev</b> {_FLAGS.get(contact.locale, '')}\n\n"
        f"<b>Имя:</b> {html.escape(contact.name)}\n"
        f"<b>Ответить:</b> {html.escape(contact.reply)}\n\n"
        f"<blockquote expandable>{html.escape(contact.message)}</blockquote>\n"
        f"<i>{contact.sentAt:%d.%m %H:%M} UTC · {contact.sender[:6]}</i>"
    )
