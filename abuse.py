import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPermissions
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

# Main app import
try:
    from VampirePro import app
except ImportError:
    from bot import app

# ----------------- Database Setup -----------------
mongo_client = AsyncIOMotorClient(Config.MONGO_DB_URI)
db = mongo_client["VAMPIREGCPRO_DB"]
approved_db = db["approved_users"]
warnings_db = db["warnings"]

# Bad words list
BAD_WORDS = [
    "mc", "madrachod", "madarchod", "bc", "bhenchod", "behenchod", 
    "randi", "gand", "gaand", "lund", "land", "chut", "chutiya", 
    "service", "video call", "mkc", "chuchi", "wife", "rand", "raand", 
    "maa", "behen", "sister", "step bull", "desi wife", "kaand", "kiss", 
    "gf", "bf", "available", "kutta", "kutiya", "ahhh", "fuck", "sex", 
    "x", "sexy", "seaxy", "dm", "pm", "bio", "join", "link"
]

# Super Fast Regex Matcher
ABUSE_PATTERN = re.compile(
    r"(?i)(?:" + "|".join([re.escape(word) for word in BAD_WORDS]) + r")"
)

async def is_user_approved(chat_id: int, user_id: int) -> bool:
    res = await approved_db.find_one({"chat_id": chat_id, "user_id": user_id})
    return bool(res)

async def increment_warnings(chat_id: int, user_id: int) -> int:
    doc = await warnings_db.find_one({"chat_id": chat_id, "user_id": user_id})
    current = doc["count"] if doc else 0
    new_count = current + 1
    await warnings_db.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"count": new_count}},
        upsert=True
    )
    return new_count

async def reset_warnings(chat_id: int, user_id: int):
    await warnings_db.delete_one({"chat_id": chat_id, "user_id": user_id})

# Abuse Handler
async def handle_abuse_violation(client: Client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not user_id or await is_user_approved(chat_id, user_id):
        return

    # Delete message instantly
    try:
        await message.delete()
    except Exception as e:
        print(f"[Abuse Delete Error]: {e}")

    user_mention = message.from_user.mention
    warn_count = await increment_warnings(chat_id, user_id)

    if warn_count < 3:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ **Abusive Language Warning [{warn_count}/3]**\n\n"
                f"Hey {user_mention}, bad/abusive words are strictly not allowed!\n"
                f"Your message was deleted. Reaching 3 warnings will result in an automatic **Mute**."
            )
        )
    else:
        try:
            await client.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False)
            )
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"🚫 **User Muted!**\n\n"
                    f"**User:** {user_mention}\n"
                    f"**Reason:** Exceeded maximum 3 warnings for using abusive words."
                )
            )
            await reset_warnings(chat_id, user_id)
        except Exception as e:
            await client.send_message(chat_id=chat_id, text=f"❌ **Failed to mute user:** `{e}`")

# High-Priority Message Handler
@app.on_message(filters.group & ~filters.me & (filters.text | filters.caption), group=-1)
async def check_abuse_in_group(client: Client, message: Message):
    if not message.from_user:
        return

    text_content = message.text or message.caption or ""

    if ABUSE_PATTERN.search(text_content):
        await handle_abuse_violation(client, message)
        
