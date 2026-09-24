import os
import sys
import asyncio
import time
import requests
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    ChatPermissions,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from config import Config

# Framework Requirement Import Rule
from VampirePro import app

# Storage Trackers
WARNINGS = {}       # {chat_id: {user_id: count}}
APPROVED_USERS = {} # {chat_id: [user_ids]}
SERVED_USERS = set()
SERVED_CHATS = set()

# NSFW Media Scanner via Sightengine API
def is_nsfw_media(file_path: str) -> bool:
    if not Config.SIGHTENGINE_API_USER or not Config.SIGHTENGINE_API_SECRET:
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
                
                if max(sexual_activity, sexual_display, erotica, suggestive) > 0.6:
                    return True
    except Exception as e:
        print(f"[NSFW Scanner Error]: {e}")
    return False

# Warning and Auto-Mute Handler
async def handle_nsfw_violation(client: Client, message: Message, reason: str):
    chat_id = message.chat.id
    user_id = message.from_user.id
    user_mention = message.from_user.mention

    # Bypass if user is Approved in this chat
    if chat_id in APPROVED_USERS and user_id in APPROVED_USERS[chat_id]:
        return

    if chat_id not in WARNINGS:
        WARNINGS[chat_id] = {}
    if user_id not in WARNINGS[chat_id]:
        WARNINGS[chat_id][user_id] = 0

    WARNINGS[chat_id][user_id] += 1
    warn_count = WARNINGS[chat_id][user_id]

    if warn_count < 3:
        await message.reply_text(
            f"🚨 **NSFW Warning [{warn_count}/3]**\n\n"
            f"Hey {user_mention}, your **{reason}** contains adult/NSFW content!\n"
            f"Please change or remove it. Reaching 3 warnings will result in an automatic **Mute**."
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
                f"**Reason:** Exceeded maximum warnings for sharing/displaying NSFW ({reason}) content."
            )
            WARNINGS[chat_id][user_id] = 0
        except Exception as e:
            await message.reply_text(f"❌ **Failed to mute user:** `{e}`")

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
    SERVED_USERS.add(user.id)

    # Send Notification to Logger Channel
    if Config.LOGGER_ID:
        try:
            await client.send_message(
                chat_id=Config.LOGGER_ID,
                text=(
                    f"👤 **Bot Started By User**\n\n"
                    f"• **Full Name:** {user.first_name} {user.last_name or ''}\n"
                    f"• **User ID:** `{user.id}`\n"
                    f"• **Username:** @{user.username if user.username else 'None'}"
                )
            )
        except Exception as e:
            print(f"[Logger Error]: {e}")

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
    SERVED_CHATS.add(chat_id)
    bot = await client.get_me()

    for member in message.new_chat_members:
        if member.id == bot.id:
            # Bot added to group, generate 30 min temporary link for logger
            try:
                expire_time = int(time.time()) + 1800  # 30 minutes expiration
                invite = await client.create_chat_invite_link(
                    chat_id=chat_id,
                    expire_date=expire_time,
                    member_limit=1
                )
                link_url = invite.invite_link
            except Exception:
                link_url = None

            if Config.LOGGER_ID:
                keyboard = None
                if link_url:
                    keyboard = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔗 Temporary Group Link (30m)", url=link_url)]]
                    )
                
                await client.send_message(
                    chat_id=Config.LOGGER_ID,
                    text=(
                        f"🏰 **Bot Added To New Group**\n\n"
                        f"• **Group Name:** {message.chat.title}\n"
                        f"• **Group ID:** `{chat_id}`\n"
                        f"• **Added By:** {message.from_user.mention if message.from_user else 'Unknown'}"
                    ),
                    reply_markup=keyboard
                )
        else:
            # New user join welcome & DP scan
            await message.reply_text(f"🎉 Welcome {member.mention} to **{message.chat.title}**!")
            async for photo in client.get_chat_photos(member.id, limit=1):
                file_path = await client.download_media(photo.file_id)
                if is_nsfw_media(file_path):
                    await handle_nsfw_violation(client, message, "Profile Photo (DP)")
                if os.path.exists(file_path):
                    os.remove(file_path)

# 5. Media Scanner (Stickers & GIFs)
@app.on_message(filters.group & (filters.sticker | filters.animation))
async def media_nsfw_checker(client: Client, message: Message):
    file_path = None
    media_type = "Sticker" if message.sticker else "GIF"

    try:
        file_path = await client.download_media(message)
        if is_nsfw_media(file_path):
            await message.delete()
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

    if chat_id not in APPROVED_USERS:
        APPROVED_USERS[chat_id] = []

    if target_user.id not in APPROVED_USERS[chat_id]:
        APPROVED_USERS[chat_id].append(target_user.id)
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

    if chat_id in APPROVED_USERS and target_user.id in APPROVED_USERS[chat_id]:
        APPROVED_USERS[chat_id].remove(target_user.id)
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

    # Extract text content
    broadcast_msg = message.reply_to_message if message.reply_to_message else None
    
    targets = list(SERVED_CHATS)
    if include_users:
        targets.extend(list(SERVED_USERS))

    await message.reply_text(f"🚀 Starting broadcast to {len(targets)} targets...")
    
    success = 0
    failed = 0

    for target_id in targets:
        try:
            if broadcast_msg:
                sent = await broadcast_msg.copy(chat_id=target_id)
            else:
                # Remove flags from broadcast text
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

# Startup Log Print
if __name__ == "__main__":
    print("=" * 60)
    print("VAMPIRE GC PRO Bot Started Made by Vampire King")
    print("=" * 60)
    app.run()
  
