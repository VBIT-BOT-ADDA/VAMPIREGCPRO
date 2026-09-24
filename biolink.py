import re
import asyncio
import time
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPermissions
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

# Main bot file se app ko import karein (No duplicate Client creation)
try:
    from VampirePro import app
except ImportError:
    from bot import app

# ----------------- Database Setup -----------------
mongo_client = AsyncIOMotorClient(Config.MONGO_DB_URI)
db = mongo_client["VAMPIREGCPRO_DB"]
approved_db = db["approved_users"]
warnings_db = db["warnings"]

# Comprehensive URL & Link Matching Regex
URL_REGEX = re.compile(
    r"(https?://(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|"
    r"www\.[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|"
    r"https?://[^\s]+|t\.me/[^\s]+|telegram\.me/[^\s]+|[a-zA-Z0-9-]+\.(?:com|org|net|me|in|io|co|site|xyz|online|app))",
    re.IGNORECASE
)

# Cache dictionary to store bio scan results
BIO_CACHE = {}
CACHE_TTL = 300  # Re-check user's bio after 5 minutes

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

# Bio Violation Handler (Instant Delete + Warning / Mute)
async def handle_bio_violation(client: Client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not user_id:
        return

    # Skip Approved Users
    if await is_user_approved(chat_id, user_id):
        return

    # 1. Delete user's message immediately
    try:
        await message.delete()
    except Exception as e:
        print(f"[BioLink Delete Error]: {e}")

    user_mention = message.from_user.mention
    warn_count = await increment_warnings(chat_id, user_id)

    # 2. Warning and Mute logic
    if warn_count < 3:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"🚨 **Bio Link Warning [{warn_count}/3]**\n\n"
                f"Hey {user_mention}, links/websites in profile Bio are strictly prohibited!\n"
                f"Your message was removed. Please remove the link from your Telegram Bio.\n"
                f"Reaching 3 warnings will result in an automatic **Mute**."
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
                    f"**Reason:** Promoting links in Profile Bio after 3 warnings."
                )
            )
            await reset_warnings(chat_id, user_id)
        except Exception as e:
            await client.send_message(
                chat_id=chat_id,
                text=f"❌ **Failed to mute {user_mention}:** `{e}`"
            )

# High-Speed Bio Scanner Handler
@app.on_message(filters.group & ~filters.service)
async def biolink_checker_handler(client: Client, message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    current_time = time.time()

    # Check cache first for superfast execution
    if user_id in BIO_CACHE:
        cached_data = BIO_CACHE[user_id]
        if current_time - cached_data["time"] < CACHE_TTL:
            if cached_data["has_link"]:
                await handle_bio_violation(client, message)
            return

    # Fetch user bio if not cached or cache expired
    try:
        user_info = await client.get_chat(user_id)
        bio_text = user_info.bio or ""

        # Check if bio contains link
        has_link = bool(URL_REGEX.search(bio_text))
        BIO_CACHE[user_id] = {"has_link": has_link, "time": current_time}

        if has_link:
            await handle_bio_violation(client, message)
    except Exception as e:
        print(f"[Bio Check Handled Error]: {e}")
        
