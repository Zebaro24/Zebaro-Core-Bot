import json
from html import escape

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from app.db.client import jobs_collection, github_notification_collection
from app.tg.middlewares.admin_middleware import AdminMiddleware

router = Router()
router.message.middleware(AdminMiddleware())

ALLOWED_COLLECTIONS = {
    "jobs": jobs_collection,
    "github_notification": github_notification_collection
}

ALLOWED_COMMANDS = {"find", "update_many", "insert_one"}


@router.message(Command("mongo"))
async def mongo_command(message: Message):
    if message.text.strip() == "/mongo":
        await message.answer(escape(
            "Формат команды:\n"
            "/mongo <collection> <command> <JSON>\n"
            "Примеры:\n"
            "/mongo jobs find {\"status\":\"active\"}\n"
            "/mongo jobs update_many {\"status\":\"pending\"} {\"$set\":{\"status\":\"done\"}}\n"
            "/mongo jobs insert_one {\"name\":\"New Job\",\"status\":\"pending\"}"
        ))
        return

    text = message.text[len("/mongo"):].strip()
    parts = text.split(maxsplit=2)  # collection, command, json

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

    try:
        if command == "find":
            query_json = parts[2] if len(parts) > 2 else "{}"
            query = json.loads(query_json)
            cursor = collection.find(query)
            result = [doc async for doc in cursor]

        elif command == "update_many":
            if len(parts) < 3:
                await message.answer("Для update_many нужно два JSON: query и update")
                return
            try:
                query_str, update_str = parts[2].split(maxsplit=1)
                query = json.loads(query_str)
                update = json.loads(update_str)
            except json.JSONDecodeError:
                await message.answer("Неверный формат JSON для update_many")
                return
            res = await collection.update_many(query, update)
            result = {"matched_count": res.matched_count, "modified_count": res.modified_count}

        elif command == "insert_one":
            if len(parts) < 3:
                await message.answer("Для insert_one нужен JSON документа")
                return
            try:
                doc = json.loads(parts[2])
            except json.JSONDecodeError:
                await message.answer("Неверный JSON для insert_one")
                return
            res = await collection.insert_one(doc)
            result = {"inserted_id": str(res.inserted_id)}
        else:
            await message.answer("Неверная команда")
            return

    except json.JSONDecodeError:
        await message.answer("Неверный JSON")
        return
    except Exception as e:
        await message.answer(f"Ошибка при выполнении команды: {e}")
        return

    await message.answer(f"<pre>{escape(str(result))}</pre>")
