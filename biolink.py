import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPermissions
from config import Config

# Framework Requirement Import Rule
from VampirePro import app

# Storage Trackers
BIO_WARNINGS = {}        # {chat_id: {user_id: count}}
APPROVED_BIO_USERS = {}  # {chat_id: [user_ids]}

# Regex pattern to detect URLs or Telegram Usernames/Handles (@username)
BIO_LINK_PATTERN = re.compile(
    r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}(/[^\s]*)?|@[a-zA-Z0-9_]{3,32})',
    re.IGNORECASE
)

# Function to check if bio contains any link or handle
def contains_bio_link(bio_text: str) -> bool:
    if not bio_text:
        return False
    return bool(BIO_LINK_PATTERN.search(bio_text))

# Warning and Auto-Mute Action Handler for Bio Violation
async def handle_bio_violation(client: Client, message: Message, user_id: int, user_mention: str):
    chat_id = message.chat.id

    # Check if user is approved in this chat
    if chat_id in APPROVED_BIO_USERS and user_id in APPROVED_BIO_USERS[chat_id]:
        return

    if chat_id not in BIO_WARNINGS:
        BIO_WARNINGS[chat_id] = {}
    if user_id not in BIO_WARNINGS[chat_id]:
        BIO_WARNINGS[chat_id][user_id] = 0

    BIO_WARNINGS[chat_id][user_id] += 1
    warn_count = BIO_WARNINGS[chat_id][user_id]

    if warn_count < 3:
        await message.reply_text(
            f"⚠️ **Bio Link Warning [{warn_count}/3]**\n\n"
            f"Hey {user_mention}, links or Telegram handles (`@username`) were detected in your Bio!\n"
            f"**Please remove your bio link immediately.**\n"
            f"If you do not remove it after 3 warnings, you will be automatically **Muted**."
        )
    else:
        try:
            await client.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False)
            )
            await message.reply_text(
                f"🚫 **User Muted!**\n\n"
                f"**User:** {user_mention}\n"
                f"**Reason:** Failed to remove Bio Link/Handle after 3 warnings."
            )
            BIO_WARNINGS[chat_id][user_id] = 0  # Reset warning counter
        except Exception as e:
            await message.reply_text(f"❌ **Failed to mute user:** `{e}`")

# 1. Bio Checker for Message Event in Groups
@app.on_message(filters.group & ~filters.bot, group=1)
async def check_user_bio_on_message(client: Client, message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Skip if user is approved
    if chat_id in APPROVED_BIO_USERS and user_id in APPROVED_BIO_USERS[chat_id]:
        return

    try:
        user_info = await client.get_chat(user_id)
        user_bio = user_info.bio or ""

        if contains_bio_link(user_bio):
            await handle_bio_violation(client, message, user_id, message.from_user.mention)
    except Exception as e:
        print(f"[Bio Check Error]: {e}")

# 2. Bio Checker for New Member Joining Group
@app.on_message(filters.group & filters.new_chat_members, group=2)
async def check_user_bio_on_join(client: Client, message: Message):
    for member in message.new_chat_members:
        if member.is_bot:
            continue

        try:
            user_info = await client.get_chat(member.id)
            user_bio = user_info.bio or ""

            if contains_bio_link(user_bio):
                await handle_bio_violation(client, message, member.id, member.mention)
        except Exception as e:
            print(f"[Bio Join Check Error]: {e}")

# 3. Approve User (Bypass Bio Link Checks)
@app.on_message(filters.group & filters.command("approve"))
async def approve_bio_user(client: Client, message: Message):
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply_text("❌ Only group administrators can approve users.")

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply_text("❌ Reply to a user's message to approve them.")

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if chat_id not in APPROVED_BIO_USERS:
        APPROVED_BIO_USERS[chat_id] = []

    if target_user.id not in APPROVED_BIO_USERS[chat_id]:
        APPROVED_BIO_USERS[chat_id].append(target_user.id)
        await message.reply_text(f"✅ {target_user.mention} has been approved! Bio link checks will now ignore this user.")
    else:
        await message.reply_text(f"ℹ️ {target_user.mention} is already in the approved list.")

# 4. Unapprove User (Remove Bypass Exemption)
@app.on_message(filters.group & filters.command("unapprove"))
async def unapprove_bio_user(client: Client, message: Message):
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply_text("❌ Only group administrators can unapprove users.")

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply_text("❌ Reply to a user's message to unapprove them.")

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if chat_id in APPROVED_BIO_USERS and target_user.id in APPROVED_BIO_USERS[chat_id]:
        APPROVED_BIO_USERS[chat_id].remove(target_user.id)
        await message.reply_text(f"🚫 {target_user.mention} has been unapproved. Bio link protection reactivated for this user.")
    else:
        await message.reply_text(f"ℹ️ {target_user.mention} is not in the approved list.")
      
