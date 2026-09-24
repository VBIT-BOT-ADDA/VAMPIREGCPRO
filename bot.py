import os
import sys
import asyncio
import time

# Event loop fix for Python 3.10+ and Pyrogram
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import requests
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    ChatPermissions,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

# Handle VampirePro framework import rule with safe fallback
try:
    from VampirePro import app
except ImportError:
    app = Client(
        "VAMPIREGCPRO",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN
    )

# ----------------- MongoDB Database Setup -----------------
mongo_client = AsyncIOMotorClient(Config.MONGO_DB_URI)
db = mongo_client["VAMPIREGCPRO_DB"]

users_db = db["users"]
chats_db = db["chats"]
approved_db = db["approved_users"]
warnings_db = db["warnings"]

# Helper DB Functions
async def add_served_user(user_id: int):
    await users_db.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)

async def add_served_chat(chat_id: int):
    await chats_db.update_one({"chat_id": chat_id}, {"$set": {"chat_id": chat_id}}, upsert=True)

async def get_served_users():
    users = []
    async for doc in users_db.find():
        users.append(doc["user_id"])
    return users

async def get_served_chats():
    chats = []
    async for doc in chats_db.find():
        chats.append(doc["chat_id"])
    return chats

async def is_user_approved(chat_id: int, user_id: int) -> bool:
    res = await approved_db.find_one({"chat_id": chat_id, "user_id": user_id})
    return bool(res)

async def approve_user_db(chat_id: int, user_id: int):
    await approved_db.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"chat_id": chat_id, "user_id": user_id}},
        upsert=True
    )

async def unapprove_user_db(chat_id: int, user_id: int):
    await approved_db.delete_one({"chat_id": chat_id, "user_id": user_id})

async def get_user_warnings(chat_id: int, user_id: int) -> int:
    doc = await warnings_db.find_one({"chat_id": chat_id, "user_id": user_id})
    return doc["count"] if doc else 0

async def increment_warnings(chat_id: int, user_id: int) -> int:
    current = await get_user_warnings(chat_id, user_id)
    new_count = current + 1
    await warnings_db.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"count": new_count}},
        upsert=True
    )
    return new_count

async def reset_warnings(chat_id: int, user_id: int):
    await warnings_db.delete_one({"chat_id": chat_id, "user_id": user_id})

# Safe Logger Helper Function
async def send_logger_message(client: Client, text: str, reply_markup=None):
    if hasattr(Config, "LOGGER_ID") and Config.LOGGER_ID:
        try:
            logger_id = int(str(Config.LOGGER_ID).strip())
            await client.send_message(
                chat_id=logger_id,
                text=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            print(f"[Logger Warning]: Could not send log: {e}")

# ----------------- NSFW Scanner -----------------
def is_nsfw_media(file_path: str) -> bool:
    if not getattr(Config, "SIGHTENGINE_API_USER", None) or not getattr(Config, "SIGHTENGINE_API_SECRET", None):
        return False
    
    url = "https://api.sightengine.com/1.0/check.json"
    params = {
        'models': 'nudity-2.0',
        'api_user': Config.SIGHTENGINE_API_USER,
        'api_secret': Config.SIGHTENGINE_API_SECRET
    }
    
    try:
        with open(file_path, 'rb') as img_file:
            files = {'media': img_file}
            response = requests.post(url, files=files, data=params, timeout=10)
            data = response.json()
            
            if data.get("status") == "success":
                nudity = data.get("nudity", {})
                sexual_activity = nudity.get("sexual_activity", 0)
                sexual_display = nudity.get("sexual_display", 0)
                erotica = nudity.get("erotica", 0)
                suggestive = nudity.get("suggestive", 0)
                
                if max(sexual_activity, sexual_display, erotica, suggestive) > 0.5:
                    return True
    except Exception as e:
        print(f"[NSFW Scanner Error]: {e}")
    return False

# Warning, Auto-Delete & Auto-Mute Handler
async def handle_nsfw_violation(client: Client, message: Message, reason: str):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not user_id:
        return

    # Bypass if user is Approved in MongoDB
    if await is_user_approved(chat_id, user_id):
        return

    # Always try to delete the violating message first
    try:
        await message.delete()
    except Exception as e:
        print(f"[Delete Error]: Could not delete message: {e}")

    user_mention = message.from_user.mention
    warn_count = await increment_warnings(chat_id, user_id)

    if warn_count < 3:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"🚨 **NSFW Warning [{warn_count}/3]**\n\n"
                f"Hey {user_mention}, your **{reason}** contains adult/NSFW content and was deleted!\n"
                f"Please follow the rules. Reaching 3 warnings will result in an automatic **Mute**."
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
                    f"**Reason:** Exceeded maximum warnings for sharing/displaying NSFW ({reason}) content."
                )
            )
            await reset_warnings(chat_id, user_id)
        except Exception as e:
            await client.send_message(
                chat_id=chat_id,
                text=f"❌ **Failed to mute user {user_mention}:** `{e}`"
            )

# Button Markup Generators
def build_start_buttons(bot_username: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Me To Your Group ➕", url=f"https://t.me/{bot_username}?startgroup=true")
        ],
        [
            InlineKeyboardButton("💬 Support Group", url=Config.SUPPORT_GROUP),
            InlineKeyboardButton("📢 Update Channel", url=Config.UPDATE_CHANNEL)
        ],
        [
            InlineKeyboardButton("👑 Owner", url=f"https://t.me/{Config.OWNER_USERNAME}"),
            InlineKeyboardButton("❓ Help & Commands", callback_data="help_menu")
        ]
    ])

def build_help_buttons(bot_username: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Me To Your Group ➕", url=f"https://t.me/{bot_username}?startgroup=true")
        ],
        [
            InlineKeyboardButton("🔙 Back to Start", callback_data="start_menu")
        ]
    ])

# 1. Start Command & Logger
@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    bot = await client.get_me()
    user = message.from_user
    
    # Save user to MongoDB
    await add_served_user(user.id)

    log_text = (
        f"👤 **Bot Started By User**\n\n"
        f"• **Full Name:** {user.first_name} {user.last_name or ''}\n"
        f"• **User ID:** `{user.id}`\n"
        f"• **Username:** @{user.username if user.username else 'None'}"
    )
    await send_logger_message(client, log_text)

    await message.reply_photo(
        photo=Config.START_IMG,
        caption=(
            f"👋 **Hello {user.mention}!**\n\n"
            f"🤖 Welcome to **VAMPIREGCPRO**!\n"
            f"An advanced AI-powered Telegram group moderation bot.\n\n"
            f"✨ **Core Features:**\n"
            f"• NSFW Profile Picture Scanning\n"
            f"• Adult 18+ Sticker & GIF Auto-Delete\n"
            f"• 3-Strike Warning & Auto-Mute System"
        ),
        reply_markup=build_start_buttons(bot.username)
    )

# 2. Help Command Handler
@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    bot = await client.get_me()
    await message.reply_text(
        text=(
            "📖 **VAMPIREGCPRO - Commands & System Guide**\n\n"
            "• `/start` - Start the bot\n"
            "• `/help` - Show help menu\n"
            "• `/approve` - Exclude user from NSFW checks (Admin Only)\n"
            "• `/unapprove` - Remove user from whitelist (Admin Only)\n\n"
            "👑 **Owner Broadcast Commands:**\n"
            "• `/broadcast <msg>` - Send broadcast to all Groups only.\n"
            "• `/broadcast -user <msg>` - Send broadcast to Groups and Users.\n"
            "• `/broadcast -user -pin <msg>` - Send broadcast to Groups & Users and PIN message."
        ),
        reply_markup=build_help_buttons(bot.username)
    )

# 3. Callback Queries Handler
@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    bot = await client.get_me()
    
    if query.data == "help_menu":
        await query.message.edit_text(
            text=(
                "📖 **VAMPIREGCPRO - Commands & System Guide**\n\n"
                "• `/start` - Start the bot\n"
                "• `/help` - Show help menu\n"
                "• `/approve` - Exclude user from NSFW checks (Admin Only)\n"
                "• `/unapprove` - Remove user from whitelist (Admin Only)\n\n"
                "👑 **Owner Broadcast Commands:**\n"
                "• `/broadcast <msg>` - Send broadcast to all Groups only.\n"
                "• `/broadcast -user <msg>` - Send broadcast to Groups and Users.\n"
                "• `/broadcast -user -pin <msg>` - Send broadcast to Groups & Users and PIN message."
            ),
            reply_markup=build_help_buttons(bot.username)
        )
    elif query.data == "start_menu":
        await query.message.edit_text(
            text=(
                f"👋 **Hello {query.from_user.mention}!**\n\n"
                f"🤖 Welcome to **VAMPIREGCPRO**!\n"
                f"An advanced AI-powered Telegram group moderation bot.\n\n"
                f"✨ **Core Features:**\n"
                f"• NSFW Profile Picture Scanning\n"
                f"• Adult 18+ Sticker & GIF Auto-Delete\n"
                f"• 3-Strike Warning & Auto-Mute System"
            ),
            reply_markup=build_start_buttons(bot.username)
        )

# 4. Bot Added To Group Handler with 30-Min Temporary Invite Link
@app.on_message(filters.new_chat_members)
async def new_chat_event(client: Client, message: Message):
    chat_id = message.chat.id
    await add_served_chat(chat_id)
    bot = await client.get_me()

    for member in message.new_chat_members:
        if member.id == bot.id:
            try:
                expire_time = int(time.time()) + 1800
                invite = await client.create_chat_invite_link(
                    chat_id=chat_id,
                    expire_date=expire_time,
                    member_limit=1
                )
                link_url = invite.invite_link
            except Exception:
                link_url = None

            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Temporary Group Link (30m)", url=link_url)]]) if link_url else None
            
            log_text = (
                f"🏰 **Bot Added To New Group**\n\n"
                f"• **Group Name:** {message.chat.title}\n"
                f"• **Group ID:** `{chat_id}`\n"
                f"• **Added By:** {message.from_user.mention if message.from_user else 'Unknown'}"
            )
            await send_logger_message(client, log_text, reply_markup=keyboard)

        else:
            await message.reply_text(f"🎉 Welcome {member.mention} to **{message.chat.title}**!")
            try:
                async for photo in client.get_chat_photos(member.id, limit=1):
                    file_path = await client.download_media(photo.file_id)
                    if is_nsfw_media(file_path):
                        await handle_nsfw_violation(client, message, "Profile Photo (DP)")
                    if os.path.exists(file_path):
                        os.remove(file_path)
            except Exception as e:
                print(f"[DP Scan Error]: {e}")

# 5. Media Scanner (Stickers, GIFs & Photos)
@app.on_message(filters.group & (filters.sticker | filters.animation | filters.photo))
async def media_nsfw_checker(client: Client, message: Message):
    file_path = None
    media_type = "Photo" if message.photo else ("Sticker" if message.sticker else "GIF")

    try:
        file_path = await client.download_media(message)
        if file_path and is_nsfw_media(file_path):
            await handle_nsfw_violation(client, message, media_type)
    except Exception as e:
        print(f"[Media Check Error]: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# 6. Approve & Unapprove System
@app.on_message(filters.group & filters.command("approve"))
async def approve_user(client: Client, message: Message):
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply_text("❌ Only administrators can approve users.")

    if not message.reply_to_message:
        return await message.reply_text("❌ Reply to a user's message to approve them.")

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if not await is_user_approved(chat_id, target_user.id):
        await approve_user_db(chat_id, target_user.id)
        await message.reply_text(f"✅ {target_user.mention} is now approved! Bot will ignore their content.")
    else:
        await message.reply_text(f"ℹ️ {target_user.mention} is already approved.")

@app.on_message(filters.group & filters.command("unapprove"))
async def unapprove_user(client: Client, message: Message):
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply_text("❌ Only administrators can unapprove users.")

    if not message.reply_to_message:
        return await message.reply_text("❌ Reply to a user's message to unapprove them.")

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if await is_user_approved(chat_id, target_user.id):
        await unapprove_user_db(chat_id, target_user.id)
        await message.reply_text(f"🚫 {target_user.mention} has been unapproved.")
    else:
        await message.reply_text(f"ℹ️ {target_user.mention} is not in the approved list.")

# 7. Advanced Broadcast Engine
@app.on_message(filters.command("broadcast"))
async def broadcast_handler(client: Client, message: Message):
    if message.from_user.id != Config.OWNER_ID:
        return

    if not message.reply_to_message and len(message.command) < 2:
        return await message.reply_text("❌ Provide a message or reply to a message to broadcast.")

    args = message.text.split()
    include_users = "-user" in args
    should_pin = "-pin" in args

    broadcast_msg = message.reply_to_message if message.reply_to_message else None
    
    targets = await get_served_chats()
    if include_users:
        users = await get_served_users()
        targets.extend(users)

    await message.reply_text(f"🚀 Starting broadcast to {len(targets)} targets from database...")
    
    success = 0
    failed = 0

    for target_id in targets:
        try:
            if broadcast_msg:
                sent = await broadcast_msg.copy(chat_id=target_id)
            else:
                text_to_send = " ".join([word for word in args[1:] if word not in ["-user", "-pin"]])
                sent = await client.send_message(chat_id=target_id, text=text_to_send)

            if should_pin and sent:
                try:
                    await sent.pin(disable_notification=False)
                except Exception:
                    pass

            success += 1
            await asyncio.sleep(0.3)
        except Exception:
            failed += 1

    await message.reply_text(f"✅ **Broadcast Completed!**\n\n• Success: `{success}`\n• Failed: `{failed}`")

if __name__ == "__main__":
    print("=" * 60)
    print("VAMPIRE GC PRO Bot Started Made by Vampire King")
    print("=" * 60)
    app.run()
    
