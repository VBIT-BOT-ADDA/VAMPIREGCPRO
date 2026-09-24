import os
import re
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPermissions
from config import Config

# Required framework import rule
from VampirePro import app

# Storage Trackers
ABUSE_WARNINGS = {}        # {chat_id: {user_id: count}}
APPROVED_ABUSE_USERS = {}  # {chat_id: [user_ids]}

# List of filtered bad words and abusive terms
BAD_WORDS = [
    "mc", "madrachod", "madarchod", "bc", "bhenchod", "behenchod", 
    "randi", "gand", "gaand", "lund", "land", "chut", "chutiya", 
    "service", "video call", "mkc", "chuchi", "wife", "rand", "raand", 
    "maa", "behen", "sister", "step bull", "desi wife", "kaand", "kiss", 
    "gf", "bf", "available", "kutta", "kutiya", "ahhh", "fuck", "sex", 
    "x", "sexy", "seaxy", "dm", "pm", "bio", "join", "link"
]

# Build regex pattern to match exact word occurrences (case-insensitive)
pattern_str = r'\b(' + '|'.join([re.escape(word) for word in BAD_WORDS]) + r')\b'
ABUSE_PATTERN = re.compile(pattern_str, re.IGNORECASE)

# Function to check if a message text contains any blocked terms
def contains_abuse(text: str) -> bool:
    if not text:
        return False
    return bool(ABUSE_PATTERN.search(text))

# Violation action handler: Delete message, warn, and auto-mute after 3 warnings
async def handle_abuse_violation(client: Client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    user_mention = message.from_user.mention

    # Delete the abusive message immediately
    try:
        await message.delete()
    except Exception as e:
        print(f"[Abuse Delete Error]: {e}")

    # Skip warnings/mute if user is approved in this chat
    if chat_id in APPROVED_ABUSE_USERS and user_id in APPROVED_ABUSE_USERS[chat_id]:
        return

    if chat_id not in ABUSE_WARNINGS:
        ABUSE_WARNINGS[chat_id] = {}
    if user_id not in ABUSE_WARNINGS[chat_id]:
        ABUSE_WARNINGS[chat_id][user_id] = 0

    ABUSE_WARNINGS[chat_id][user_id] += 1
    warn_count = ABUSE_WARNINGS[chat_id][user_id]

    if warn_count < 3:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ **Abusive Language Warning [{warn_count}/3]**\n\n"
                f"Hey {user_mention}, abusive/prohibited words are not allowed in this group!\n"
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
                    f"**Reason:** Exceeded maximum warnings for using abusive language."
                )
            )
            ABUSE_WARNINGS[chat_id][user_id] = 0  # Reset counter
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

    if chat_id not in APPROVED_ABUSE_USERS:
        APPROVED_ABUSE_USERS[chat_id] = []

    if target_user.id not in APPROVED_ABUSE_USERS[chat_id]:
        APPROVED_ABUSE_USERS[chat_id].append(target_user.id)
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

    if chat_id in APPROVED_ABUSE_USERS and target_user.id in APPROVED_ABUSE_USERS[chat_id]:
        APPROVED_ABUSE_USERS[chat_id].remove(target_user.id)
        await message.reply_text(f"🚫 {target_user.mention} has been unapproved. Anti-abuse filter reactivated for this user.")
    else:
        await message.reply_text(f"ℹ️ {target_user.mention} is not in the approved list.")
      
