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
    await users_db.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id}},
        upsert=True
    )

async def add_served_chat(chat_id: int):
    await chats_db.update_one(
        {"chat_id": chat_id},
        {"$set": {"chat_id": chat_id}},
        upsert=True
    )

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

# ----------------- Safe Logger -----------------
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
    if not getattr(Config, "SIGHTENGINE_API_USER", None) or not getattr(
        Config, "SIGHTENGINE_API_SECRET", None
    ):
        print("[NSFW Scanner] Sightengine credentials are missing.")
        return False

    url = "https://api.sightengine.com/1.0/check.json"
    params = {
        "models": "nudity-2.0",
        "api_user": Config.SIGHTENGINE_API_USER,
        "api_secret": Config.SIGHTENGINE_API_SECRET,
    }

    try:
        with open(file_path, "rb") as img_file:
            files = {"media": img_file}
            response = requests.post(
                url,
                files=files,
                data=params,
                timeout=20
            )
            response.raise_for_status()
            data = response.json()

        if data.get("status") == "success":
            nudity = data.get("nudity", {})
            sexual_activity = float(nudity.get("sexual_activity", 0) or 0)
            sexual_display = float(nudity.get("sexual_display", 0) or 0)
            erotica = float(nudity.get("erotica", 0) or 0)
            suggestive = float(nudity.get("suggestive", 0) or 0)

            score = max(
                sexual_activity,
                sexual_display,
                erotica,
                suggestive
            )

            print(f"[NSFW Scanner] score={score:.3f} file={file_path}")
            return score > 0.5

        print(f"[NSFW Scanner] API response was not successful: {data}")

    except Exception as e:
        print(f"[NSFW Scanner Error]: {e}")

    return False

# ----------------- Admin / Owner Protection -----------------
async def is_admin_or_owner(client: Client, chat_id: int, user_id: int) -> bool:
    """Return True when the user is the group owner/admin or configured bot owner."""
    if not user_id:
        return True

    # Configured global owner is always protected.
    try:
        if int(user_id) == int(Config.OWNER_ID):
            return True
    except (AttributeError, TypeError, ValueError):
        pass

    try:
        member = await client.get_chat_member(chat_id, user_id)
        return str(member.status).lower() in {
            "administrator",
            "owner",
            "creator",
        }
    except Exception as e:
        # If Telegram cannot verify the member, do NOT treat them as admin.
        # This keeps normal-user moderation working while avoiding a crash.
        print(
            f"[Admin Check] Could not check user {user_id} "
            f"in chat {chat_id}: {e}"
        )
        return False


# ----------------- Warning / Delete / Mute -----------------
async def handle_nsfw_violation(
    client: Client,
    message: Message,
    reason: str
):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not user_id:
        return

    await handle_nsfw_user_violation(
        client=client,
        chat_id=chat_id,
        user_id=user_id,
        reason=reason,
        message=message
    )

async def handle_nsfw_user_violation(
    client: Client,
    chat_id: int,
    user_id: int,
    reason: str,
    message: Message = None
):
    if not user_id:
        return

    # IMPORTANT: Never moderate/delete/warn/mute group admins, owners,
    # or the configured bot owner.
    if await is_admin_or_owner(client, chat_id, user_id):
        print(
            f"[NSFW] Skipped admin/owner {user_id} "
            f"in chat {chat_id}"
        )
        return

    # Approved users bypass NSFW checks.
    if await is_user_approved(chat_id, user_id):
        print(
            f"[NSFW] Skipped approved user {user_id} "
            f"in chat {chat_id}"
        )
        return

    # Delete the offending message when one exists.
    if message is not None:
        try:
            await message.delete()
        except Exception as e:
            print(f"[Delete Error]: Could not delete message: {e}")

    # Get user information for mention/name.
    try:
        user = await client.get_users(user_id)
        user_mention = user.mention
    except Exception:
        user_mention = f"`{user_id}`"

    warn_count = await increment_warnings(chat_id, user_id)

    if warn_count < 3:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"🚨 **NSFW Warning [{warn_count}/3]**\n\n"
                f"Hey {user_mention}, your **{reason}** "
                f"contains adult/NSFW content and was removed!\n"
                f"Please follow the group rules. "
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
                    f"**Reason:** Exceeded maximum 3 warnings "
                    f"for NSFW ({reason}) content."
                )
            )

            await reset_warnings(chat_id, user_id)

        except Exception as e:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ **Failed to mute user {user_mention}:** `{e}`"
                )
            )

# ----------------- Button Markup -----------------
def build_start_buttons(bot_username: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Add Me To Your Group ➕",
                url=f"https://t.me/{bot_username}?startgroup=true"
            )
        ],
        [
            InlineKeyboardButton(
                "💬 Support Group",
                url=Config.SUPPORT_GROUP
            ),
            InlineKeyboardButton(
                "📢 Update Channel",
                url=Config.UPDATE_CHANNEL
            )
        ],
        [
            InlineKeyboardButton(
                "👑 Owner",
                url=f"https://t.me/{Config.OWNER_USERNAME}"
            ),
            InlineKeyboardButton(
                "❓ Help & Commands",
                callback_data="help_menu"
            )
        ]
    ])

def build_help_buttons(bot_username: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Add Me To Your Group ➕",
                url=f"https://t.me/{bot_username}?startgroup=true"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Start",
                callback_data="start_menu"
            )
        ]
    ])

# ----------------- 1. Start Command -----------------
@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    bot = await client.get_me()
    user = message.from_user

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

# ----------------- 2. Help Command -----------------
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

# ----------------- 3. Callback Queries -----------------
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

# ----------------- 4. Bot Added + NEW MEMBER DP SCANNER -----------------
@app.on_message(filters.new_chat_members)
async def new_chat_event(client: Client, message: Message):
    chat_id = message.chat.id
    await add_served_chat(chat_id)
    bot = await client.get_me()

    for member in message.new_chat_members:

        # Bot itself was added to a group.
        if member.id == bot.id:
            try:
                expire_time = int(time.time()) + 1800
                invite = await client.create_chat_invite_link(
                    chat_id=chat_id,
                    expire_date=expire_time,
                    member_limit=1
                )
                link_url = invite.invite_link
            except Exception as e:
                print(f"[Invite Link Error]: {e}")
                link_url = None

            keyboard = (
                InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🔗 Temporary Group Link (30m)",
                            url=link_url
                        )
                    ]
                ])
                if link_url
                else None
            )

            log_text = (
                f"🏰 **Bot Added To New Group**\n\n"
                f"• **Group Name:** {message.chat.title}\n"
                f"• **Group ID:** `{chat_id}`\n"
                f"• **Added By:** "
                f"{message.from_user.mention if message.from_user else 'Unknown'}"
            )
            await send_logger_message(
                client,
                log_text,
                reply_markup=keyboard
            )
            continue

        # ----------------- NEW MEMBER DP CHECK -----------------
        # IMPORTANT:
        # message.from_user is NOT necessarily the new member.
        # We therefore use `member.id` everywhere for the DP scan
        # and warning/mute operation.
        await add_served_user(member.id)

        # Admins/owners are never scanned or moderated.
        if await is_admin_or_owner(client, chat_id, member.id):
            print(
                f"[DP Scanner] Skipping admin/owner {member.id}"
            )
            try:
                await message.reply_text(
                    f"🎉 Welcome {member.mention} to **{message.chat.title}**!"
                )
            except Exception as e:
                print(f"[Welcome Error]: {e}")
            continue

        try:
            print(
                f"[DP Scanner] New member joined: "
                f"{member.id} ({member.first_name})"
            )

            # Check whether this user is already approved.
            if await is_user_approved(chat_id, member.id):
                print(
                    f"[DP Scanner] Skipping approved user {member.id}"
                )
            else:
                dp_found = False

                # Telegram can have more than one profile photo.
                # We only need the newest/current one.
                async for photo in client.get_chat_photos(
                    member.id,
                    limit=1
                ):
                    dp_found = True

                    dp_path = None

                    try:
                        # Download the actual profile photo.
                        dp_path = await client.download_media(
                            photo.file_id
                        )

                        if not dp_path or not os.path.exists(dp_path):
                            print(
                                f"[DP Scanner] Could not download DP "
                                f"for user {member.id}"
                            )
                            break

                        print(
                            f"[DP Scanner] Downloaded DP for "
                            f"{member.id}: {dp_path}"
                        )

                        # Send image to Sightengine.
                        is_nsfw = is_nsfw_media(dp_path)

                        if is_nsfw:
                            print(
                                f"[DP Scanner] NSFW DP detected for "
                                f"user {member.id}"
                            )

                            # IMPORTANT:
                            # Use member.id, not message.from_user.id.
                            # This makes the warning/mute apply to the
                            # actual new member.
                            await handle_nsfw_user_violation(
                                client=client,
                                chat_id=chat_id,
                                user_id=member.id,
                                reason="Profile Photo (DP)"
                            )

                            # If the user is NSFW, also try to remove
                            # their current profile photo from our local
                            # downloaded file only. Telegram's original
                            # profile photo is NOT modified.
                        else:
                            print(
                                f"[DP Scanner] DP is OK for user "
                                f"{member.id}"
                            )

                    except Exception as e:
                        print(
                            f"[DP Scanner] Error while checking "
                            f"user {member.id}: {e}"
                        )

                    finally:
                        if dp_path and os.path.exists(dp_path):
                            try:
                                os.remove(dp_path)
                            except Exception as e:
                                print(
                                    f"[DP Scanner] File cleanup error: {e}"
                                )

                    # Only newest DP is needed.
                    break

                if not dp_found:
                    print(
                        f"[DP Scanner] User {member.id} has no "
                        f"accessible profile photo."
                    )

        except Exception as e:
            print(
                f"[DP Scanner] Failed for new member "
                f"{member.id}: {e}"
            )

        # Normal welcome message.
        try:
            await message.reply_text(
                f"🎉 Welcome {member.mention} to **{message.chat.title}**!"
            )
        except Exception as e:
            print(f"[Welcome Error]: {e}")

# ----------------- 5. Group Media Scanner -----------------
@app.on_message(
    filters.group & (filters.sticker | filters.animation | filters.photo)
)
async def media_nsfw_checker(client: Client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not user_id:
        return

    # Admins/owners are completely ignored by the NSFW media scanner.
    if await is_admin_or_owner(client, chat_id, user_id):
        return

    if await is_user_approved(chat_id, user_id):
        return

    # Video / animated stickers may not be directly supported by
    # the image scanner, so handle them as a violation as before.
    if message.sticker and (
        message.sticker.is_video or message.sticker.is_animated
    ):
        await handle_nsfw_violation(
            client,
            message,
            "Video/Animated Sticker"
        )
        return

    file_path = None
    media_type = (
        "Photo"
        if message.photo
        else ("Sticker" if message.sticker else "GIF")
    )

    try:
        file_path = await client.download_media(message)

        if file_path and os.path.exists(file_path):
            if is_nsfw_media(file_path):
                await handle_nsfw_violation(
                    client,
                    message,
                    media_type
                )

    except Exception as e:
        print(f"[Media Check Handled Error]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

# ----------------- 6. Approve / Unapprove -----------------
@app.on_message(filters.group & filters.command("approve"))
async def approve_user(client: Client, message: Message):
    member = await client.get_chat_member(
        message.chat.id,
        message.from_user.id
    )

    if member.status not in ["administrator", "creator"]:
        return await message.reply_text(
            "❌ Only administrators can approve users."
        )

    if not message.reply_to_message:
        return await message.reply_text(
            "❌ Reply to a user's message to approve them."
        )

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if not await is_user_approved(chat_id, target_user.id):
        await approve_user_db(chat_id, target_user.id)
        await message.reply_text(
            f"✅ {target_user.mention} is now approved! "
            f"Bot will ignore their content."
        )
    else:
        await message.reply_text(
            f"ℹ️ {target_user.mention} is already approved."
        )

@app.on_message(filters.group & filters.command("unapprove"))
async def unapprove_user(client: Client, message: Message):
    member = await client.get_chat_member(
        message.chat.id,
        message.from_user.id
    )

    if member.status not in ["administrator", "creator"]:
        return await message.reply_text(
            "❌ Only administrators can unapprove users."
        )

    if not message.reply_to_message:
        return await message.reply_text(
            "❌ Reply to a user's message to unapprove them."
        )

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id

    if await is_user_approved(chat_id, target_user.id):
        await unapprove_user_db(chat_id, target_user.id)
        await message.reply_text(
            f"🚫 {target_user.mention} has been unapproved."
        )
    else:
        await message.reply_text(
            f"ℹ️ {target_user.mention} is not in the approved list."
        )

# ----------------- 7. Broadcast Engine -----------------
@app.on_message(filters.command("broadcast"))
async def broadcast_handler(client: Client, message: Message):
    if not message.from_user:
        return

    if message.from_user.id != Config.OWNER_ID:
        return

    if not message.reply_to_message and len(message.command) < 2:
        return await message.reply_text(
            "❌ Provide a message or reply to a message to broadcast."
        )

    args = message.text.split()
    include_users = "-user" in args
    should_pin = "-pin" in args

    broadcast_msg = (
        message.reply_to_message
        if message.reply_to_message
        else None
    )

    targets = await get_served_chats()

    if include_users:
        users = await get_served_users()
        targets.extend(users)

    # Remove duplicates.
    targets = list(dict.fromkeys(targets))

    await message.reply_text(
        f"🚀 Starting broadcast to {len(targets)} targets from database..."
    )

    success = 0
    failed = 0

    for target_id in targets:
        try:
            if broadcast_msg:
                sent = await broadcast_msg.copy(chat_id=target_id)
            else:
                text_to_send = " ".join(
                    [
                        word
                        for word in args[1:]
                        if word not in ["-user", "-pin"]
                    ]
                )
                sent = await client.send_message(
                    chat_id=target_id,
                    text=text_to_send
                )

            if should_pin and sent:
                try:
                    await sent.pin(disable_notification=False)
                except Exception:
                    pass

            success += 1
            await asyncio.sleep(0.3)

        except Exception:
            failed += 1

    await message.reply_text(
        f"✅ **Broadcast Completed!**\n\n"
        f"• Success: `{success}`\n"
        f"• Failed: `{failed}`"
    )

# ----------------- START -----------------
if __name__ == "__main__":
    print("=" * 60)
    print("VAMPIRE GC PRO Bot Started Made by Vampire King")
    print("=" * 60)
    app.run()
