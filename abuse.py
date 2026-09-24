import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPermissions
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

# Required framework import rule
try:
    from VampirePro import app
except ImportError:
    app = Client(
        "VAMPIREGCPRO",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN
    )

# ----------------- Database Setup (MongoDB) -----------------
mongo_client = AsyncIOMotorClient(Config.MONGO_DB_URI)
db = mongo_client["VAMPIREGCPRO_DB"]
approved_db = db["approved_users"]
warnings_db = db["warnings"]

# List of filtered bad words and abusive terms
BAD_WORDS = [
    "mc", "madrachod", "madarchod", "bc", "bhenchod", "behenchod", 
    "randi", "gand", "gaand", "lund", "land", "chut", "chutiya", 
    "service", "video call", "mkc", "chuchi", "wife", "rand", "raand", 
    "maa", "behen", "sister", "step bull", "desi wife", "kaand", "kiss", 
    "gf", "bf", "available", "kutta", "kutiya", "ahhh", "fuck", "sex", 
    "x", "sexy", "seaxy", "dm", "pm", "bio", "join", "link"
]

# Robust Regex Pattern (Matches exact words as well as words connected with symbols/punctuations)
pattern_str = r'(?i)(?:\b|_|(?<=\W))(' + '|'.join([re.escape(word) for word in BAD_WORDS]) + r')(?:\b|_|(?=\W))'
ABUSE_PATTERN = re.compile(pattern_str)

# Helper DB Functions
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

# Function to check if text contains abusive terms
def contains_abuse(text: str) -> bool:
    if not text:
        return False
    return bool(ABUSE_PATTERN.search(text))

# Violation Handler: Immediate Delete -> Warning -> Auto-Mute after 3 Strikes
async def handle_abuse_violation(client: Client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not user_id:
        return

    # Skip check if user is approved in MongoDB
    if await is_user_approved(chat_id, user_id):
        return

    # 1. Delete the abusive message immediately
    try:
        await message.delete()
    except Exception as e:
        print(f"[Abuse Delete Error]: {e}")

    user_mention = message.from_user.mention
    warn_count = await increment_warnings(chat_id, user_id)

    # 2. Warning and Mute Logic
    if warn_count < 3:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ **Abusive Language Warning [{warn_count}/3]**\n\n"
                f"Hey {user_mention}, abusive/prohibited words are strictly not allowed in this group!\n"
                f"Your message has been deleted. Reaching 3 warnings will result in an automatic **Mute**."
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
                    f"**Reason:** Exceeded maximum 3 warnings for using abusive language."
                )
            )
            await reset_warnings(chat_id, user_id)
        except Exception as e:
            await client.send_message(chat_id=chat_id, text=f"❌ **Failed to mute user:** `{e}`")

# 1. Message Handler for Group Abuse Scanning
@app.on_message(filters.group & ~filters.bot & (filters.text | filters.caption), group=3)
async def check_abuse_in_group(client: Client, message: Message):
    if not message.from_user:
        return

    text_content = message.text or message.caption or ""

    if contains_abuse(text_content):
        await handle_abuse_violation(client, message)

# 2. Command to Approve User (Exempt from Abuse Filter)
@app.on_message(filters.group & filters.command("approve"))
async def approve_abuse_user(client: Client, message: Message):
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply_text("❌ Only group administrators can approve users.")

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply_text("❌ Reply to a user's message to approve them.")

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if not await is_user_approved(chat_id, target_user.id):
        await approved_db.update_one(
            {"chat_id": chat_id, "user_id": target_user.id},
            {"$set": {"chat_id": chat_id, "user_id": target_user.id}},
            upsert=True
        )
        await message.reply_text(f"✅ {target_user.mention} is now approved! Anti-abuse filter will ignore this user.")
    else:
        await message.reply_text(f"ℹ️ {target_user.mention} is already approved.")

# 3. Command to Unapprove User (Remove Exemption)
@app.on_message(filters.group & filters.command("unapprove"))
async def unapprove_abuse_user(client: Client, message: Message):
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply_text("❌ Only group administrators can unapprove users.")

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply_text("❌ Reply to a user's message to unapprove them.")

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if await is_user_approved(chat_id, target_user.id):
        await approved_db.delete_one({"chat_id": chat_id, "user_id": target_user.id})
        await message.reply_text(f"🚫 {target_user.mention} has been unapproved. Anti-abuse filter reactivated for this user.")
    else:
        await message.reply_text(f"ℹ️ {target_user.mention} is not in the approved list.")
    
