import json
import logging
from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.db.client import github_notification_collection, jobs_collection
from src.interfaces.tg.middlewares.admin import AdminMiddleware

logger = logging.getLogger("tg.handlers.admin.mongo")

router = Router()
router.message.middleware(AdminMiddleware())

ALLOWED_COLLECTIONS = {
    "jobs": jobs_collection,
    "github_notification": github_notification_collection,
}
ALLOWED_COMMANDS = {"find", "update_many", "insert_one"}

_USAGE = (
    "Формат команды:\n"
    "/mongo <collection> <command> <JSON>\n\n"
    "Примеры:\n"
    '/mongo jobs find {"status":"active"}\n'
    '/mongo jobs update_many {"status":"pending"} {"$set":{"status":"done"}}\n'
    '/mongo jobs insert_one {"name":"New Job","status":"pending"}'
)


@router.message(Command("mongo"))
async def mongo_command(message: Message) -> None:
    text = (message.text or "").strip()

    if text == "/mongo":
        await message.answer(escape(_USAGE))
        return

    parts = text[len("/mongo") :].strip().split(maxsplit=2)

    if len(parts) < 2:
        await message.answer(escape("Использование: /mongo <collection> <command> <JSON>"))
        return

    collection_name, command = parts[0], parts[1]

    if collection_name not in ALLOWED_COLLECTIONS:
        await message.answer(f"Недопустимая коллекция: {collection_name}")
        return

    if command not in ALLOWED_COMMANDS:
        await message.answer(f"Недопустимая команда: {command}")
        return

    collection = ALLOWED_COLLECTIONS[collection_name]
    logger.info("Mongo command: collection=%s command=%s", collection_name, command)

    try:
        if command == "find":
            query = json.loads(parts[2] if len(parts) > 2 else "{}")
            result = str([doc async for doc in collection.find(query)])

        elif command == "update_many":
            if len(parts) < 3:
                await message.answer("Для update_many нужно два JSON: query и update")
                return
            try:
                query_str, update_str = parts[2].split(maxsplit=1)
                query = json.loads(query_str)
                update = json.loads(update_str)
            except (json.JSONDecodeError, ValueError):
                await message.answer("Неверный формат JSON для update_many")
                return
            res = await collection.update_many(query, update)
            result = str({"matched_count": res.matched_count, "modified_count": res.modified_count})

        elif command == "insert_one":
            if len(parts) < 3:
                await message.answer("Для insert_one нужен JSON документа")
                return
            try:
                doc = json.loads(parts[2])
            except json.JSONDecodeError:
                await message.answer("Неверный JSON для insert_one")
                return
            insert_res = await collection.insert_one(doc)
            result = str({"inserted_id": str(insert_res.inserted_id)})

        else:
            await message.answer("Неверная команда")
            return

    except json.JSONDecodeError:
        await message.answer("Неверный JSON")
        return
    except Exception as e:
        logger.exception("Mongo command failed: %s", e)
        await message.answer(f"Ошибка при выполнении команды: {e}")
        return

    await message.answer(f"<pre>{escape(result)[:4000]}</pre>")
