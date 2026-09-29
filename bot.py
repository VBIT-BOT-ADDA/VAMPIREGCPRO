import os
import asyncio
import time
import requests
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import (
    Message,
    ChatPermissions,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

from config import Config


# ============================================================
# EVENT LOOP FIX
# ============================================================

try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)


# ============================================================
# APP IMPORT
# ============================================================

try:
    from VampirePro import app
except ImportError:
    try:
        from bot import app
    except ImportError:
        app = Client(
            "VAMPIREGCPRO",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
        )


# ============================================================
# DATABASE
# ============================================================

mongo_client = AsyncIOMotorClient(
    Config.MONGO_DB_URI
)

db = mongo_client["VAMPIREGCPRO_DB"]

users_db = db["users"]
chats_db = db["chats"]
approved_db = db["approved_users"]
warnings_db = db["warnings"]


# ============================================================
# PROFILE SCAN CACHE
# ============================================================

PROFILE_SCAN_CACHE = {}
PROFILE_SCAN_LOCKS = {}
PROFILE_CACHE_LIMIT = 5000


def get_profile_lock(user_id: int):
    lock = PROFILE_SCAN_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        PROFILE_SCAN_LOCKS[user_id] = lock
    return lock


def cleanup_profile_cache():
    if len(PROFILE_SCAN_CACHE) <= PROFILE_CACHE_LIMIT:
        return
    try:
        oldest = sorted(
            PROFILE_SCAN_CACHE.items(),
            key=lambda item: item[1].get("time", 0),
        )[:500]

        for key, _ in oldest:
            PROFILE_SCAN_CACHE.pop(key, None)
    except Exception as e:
        print(f"[Profile Cache Cleanup Error] {e}")


# ============================================================
# DATABASE HELPERS
# ============================================================

async def add_served_user(user_id: int):
    if not user_id:
        return
    try:
        await users_db.update_one(
            {"user_id": int(user_id)},
            {"$set": {"user_id": int(user_id)}},
            upsert=True,
        )
    except Exception as e:
        print(f"[Served User DB Error] {e}")


async def add_served_chat(chat_id: int):
    if not chat_id:
        return
    try:
        await chats_db.update_one(
            {"chat_id": int(chat_id)},
            {"$set": {"chat_id": int(chat_id)}},
            upsert=True,
        )
    except Exception as e:
        print(f"[Served Chat DB Error] {e}")


async def get_served_users():
    users = []
    try:
        async for doc in users_db.find({}):
            if doc.get("user_id"):
                users.append(int(doc["user_id"]))
    except Exception as e:
        print(f"[Get Served Users Error] {e}")
    return users


async def get_served_chats():
    chats = []
    try:
        async for doc in chats_db.find({}):
            if doc.get("chat_id"):
                chats.append(int(doc["chat_id"]))
    except Exception as e:
        print(f"[Get Served Chats Error] {e}")
    return chats


async def is_user_approved(chat_id: int, user_id: int) -> bool:
    try:
        result = await approved_db.find_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )
        return bool(result)
    except Exception as e:
        print(f"[Approved Check Error] {e}")
        return False


async def approve_user_db(chat_id: int, user_id: int):
    try:
        await approved_db.update_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            },
            {
                "$set": {
                    "chat_id": int(chat_id),
                    "user_id": int(user_id),
                }
            },
            upsert=True,
        )
    except Exception as e:
        print(f"[Approve DB Error] {e}")


async def unapprove_user_db(chat_id: int, user_id: int):
    try:
        await approved_db.delete_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )
    except Exception as e:
        print(f"[Unapprove DB Error] {e}")


async def get_user_warnings(chat_id: int, user_id: int) -> int:
    try:
        doc = await warnings_db.find_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )
        if not doc:
            return 0
        return int(doc.get("count", 0))
    except Exception as e:
        print(f"[Warning Read Error] {e}")
        return 0


async def increment_warnings(chat_id: int, user_id: int) -> int:
    result = await warnings_db.find_one_and_update(
        {
            "chat_id": int(chat_id),
            "user_id": int(user_id),
        },
        {"$inc": {"count": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        return 1
    return int(result.get("count", 1))


async def reset_warnings(chat_id: int, user_id: int):
    try:
        await warnings_db.delete_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )
    except Exception as e:
        print(f"[Warning Reset Error] {e}")


# ============================================================
# USER DISPLAY & HELPERS
# ============================================================

def get_user_username(user):
    if not user:
        return "None"
    if user.username:
        return f"@{user.username}"
    return "None"


def get_user_full_name(user):
    if not user:
        return "Unknown"
    first = user.first_name or ""
    last = user.last_name or ""
    name = f"{first} {last}".strip()
    return name if name else "Unknown"


def get_owner_id():
    try:
        return int(str(getattr(Config, "OWNER_ID", 0)).strip())
    except Exception:
        return 0


async def send_logger_message(client: Client, text: str, reply_markup=None):
    logger_id = getattr(Config, "LOGGER_ID", None)
    if not logger_id:
        return False
    try:
        logger_id = int(str(logger_id).strip())
        await client.send_message(
            chat_id=logger_id,
            text=text,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        print(f"[Logger Error] Could not send logger message: {e}")
        return False


async def is_admin_or_owner(client: Client, chat_id: int, user_id: int) -> bool:
    if not user_id:
        return True
    try:
        owner_id = get_owner_id()
        if owner_id and int(user_id) == owner_id:
            return True
    except Exception:
        pass

    try:
        member = await client.get_chat_member(chat_id, user_id)
        if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return True
    except Exception as e:
        print(f"[Admin Check] Failed for {user_id} in {chat_id}: {e}")
    return False


# ============================================================
# ADVANCED NSFW STICKER / MEDIA SCANNER ENGINE
# ============================================================

def is_nsfw_media(file_path: str):
    """
    Enhanced Multi-Check NSFW Engine supporting Images, Static & Animated Stickers.
    """
    api_user = getattr(Config, "SIGHTENGINE_API_USER", None)
    api_secret = getattr(Config, "SIGHTENGINE_API_SECRET", None)

    if not api_user or not api_secret:
        print("[NSFW Scanner] Sightengine credentials missing.")
        return None

    if not file_path or not os.path.exists(file_path):
        print("[NSFW Scanner] File does not exist.")
        return None

    url = "https://api.sightengine.com/1.0/check.json"
    params = {
        "models": "nudity-2.0,wad",
        "api_user": api_user,
        "api_secret": api_secret,
    }

    try:
        with open(file_path, "rb") as image_file:
            response = requests.post(
                url,
                files={"media": image_file},
                data=params,
                timeout=20,
            )

        response.raise_for_status()
        data = response.json()

        if data.get("status") != "success":
            print(f"[NSFW Scanner] API status not success: {data}")
            return None

        nudity = data.get("nudity", {})
        sexual_activity = float(nudity.get("sexual_activity", 0) or 0)
        sexual_display = float(nudity.get("sexual_display", 0) or 0)
        erotica = float(nudity.get("erotica", 0) or 0)
        suggestive = float(nudity.get("suggestive", 0) or 0)

        # Additional weapon/alcohol/adult detection
        score = max(sexual_activity, sexual_display, erotica, suggestive)
        print(f"[NSFW Scanner] score={score:.3f} file={file_path}")

        # Lower threshold slightly for stickers to catch explicit adult/18+ poses
        return score > 0.42

    except Exception as e:
        print(f"[NSFW Scanner Error] {e}")
        return None


# ============================================================
# GET USER MENTION & WARNINGS
# ============================================================

async def get_user_mention(client: Client, user_id: int):
    try:
        user = await client.get_users(user_id)
        return user.mention
    except Exception:
        return f"`{user_id}`"


async def send_nsfw_warning(
    client: Client,
    chat_id: int,
    user_id: int,
    reason: str,
    warn_count: int,
):
    user_mention = await get_user_mention(client, user_id)
    try:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"🚨 **NSFW Warning [{warn_count}/3]**\n\n"
                f"Hey {user_mention}, your **{reason}** contains "
                f"adult/18+ NSFW content and was removed.\n\n"
                f"Please follow group rules. 3 warnings result in **Mute**."
            ),
        )
        print(f"[NSFW Warning] {warn_count}/3 -> {user_id}")
        return True
    except Exception as e:
        print(f"[NSFW Warning Error] {user_id}: {e}")
        return False


# ============================================================
# CENTRAL NSFW VIOLATION HANDLER
# ============================================================

async def handle_nsfw_user_violation(
    client: Client,
    chat_id: int,
    user_id: int,
    reason: str,
    message: Message = None,
):
    if not user_id:
        return False

    if await is_admin_or_owner(client, chat_id, user_id):
        return False

    if await is_user_approved(chat_id, user_id):
        return False

    # Immediate Message Delete
    if message is not None:
        try:
            await message.delete()
            print(f"[NSFW] Triggering message deleted from {user_id}")
        except Exception as e:
            print(f"[NSFW Delete Error] {user_id}: {e}")

    try:
        warn_count = await increment_warnings(chat_id, user_id)
    except Exception as e:
        print(f"[Warning DB Error] {user_id}: {e}")
        return False

    if warn_count < 3:
        await send_nsfw_warning(
            client=client,
            chat_id=chat_id,
            user_id=user_id,
            reason=reason,
            warn_count=warn_count,
        )
        return True

    user_mention = await get_user_mention(client, user_id)

    try:
        await client.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
        )

        try:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"🚫 **User Muted!**\n\n"
                    f"**User:** {user_mention}\n"
                    f"**Reason:** Reached 3/3 NSFW/18+ content warnings."
                ),
            )
        except Exception as e:
            print(f"[Mute Message Error] {e}")

        await reset_warnings(chat_id, user_id)
        return True

    except Exception as e:
        print(f"[Mute Error] Could not mute {user_id}: {e}")
        return False


async def handle_nsfw_violation(client: Client, message: Message, reason: str):
    if not message.from_user:
        return False

    return await handle_nsfw_user_violation(
        client=client,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        reason=reason,
        message=message,
    )


# ============================================================
# CURRENT PROFILE PHOTO SCANNER
# ============================================================

async def get_current_profile_photo(client: Client, user_id: int):
    try:
        user = await client.get_users(user_id)
        if not user or not user.photo:
            return None

        file_id = getattr(user.photo, "big_file_id", None) or getattr(
            user.photo, "small_file_id", None
        )
        return file_id
    except Exception as e:
        print(f"[DP Scanner] Could not get profile photo for {user_id}: {e}")
        return None


async def scan_current_profile_photo(client: Client, user_id: int):
    lock = get_profile_lock(user_id)

    async with lock:
        file_id = await get_current_profile_photo(client, user_id)

        if not file_id:
            return False, False

        cache = PROFILE_SCAN_CACHE.get(user_id)

        if cache and cache.get("file_id") == file_id:
            return True, bool(cache.get("is_nsfw", False))

        dp_path = None
        try:
            dp_path = await client.download_media(file_id)

            if not dp_path or not os.path.exists(dp_path):
                return True, False

            scan_result = await asyncio.to_thread(is_nsfw_media, dp_path)

            if scan_result is None:
                return True, False

            nsfw = bool(scan_result)

            PROFILE_SCAN_CACHE[user_id] = {
                "file_id": file_id,
                "is_nsfw": nsfw,
                "time": time.time(),
            }

            cleanup_profile_cache()
            return True, nsfw

        except Exception as e:
            print(f"[DP Scanner Error] {user_id}: {e}")
            return True, False

        finally:
            if dp_path and os.path.exists(dp_path):
                try:
                    os.remove(dp_path)
                except Exception:
                    pass


# ============================================================
# PROFILE SCAN ON EVERY MESSAGE (GROUP=-10)
# ============================================================

@app.on_message(filters.group, group=-10)
async def profile_scan_every_message(client: Client, message: Message):
    if getattr(message, "service", None) or not message.from_user:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    if getattr(message.from_user, "is_bot", False):
        return

    if await is_admin_or_owner(client, chat_id, user_id):
        return

    if await is_user_approved(chat_id, user_id):
        return

    has_photo, nsfw = await scan_current_profile_photo(client, user_id)

    if not has_photo:
        return

    if nsfw:
        await handle_nsfw_user_violation(
            client=client,
            chat_id=chat_id,
            user_id=user_id,
            reason="Profile Photo (DP)",
            message=message,
        )


# ============================================================
# NEW MEMBER JOIN EVENT
# ============================================================

@app.on_message(filters.new_chat_members)
async def new_chat_event(client: Client, message: Message):
    chat_id = message.chat.id
    await add_served_chat(chat_id)

    try:
        bot = await client.get_me()
    except Exception as e:
        print(f"[Bot Info Error] {e}")
        return

    for member in message.new_chat_members:
        if member.id == bot.id:
            continue

        await add_served_user(member.id)

        if await is_admin_or_owner(client, chat_id, member.id) or await is_user_approved(chat_id, member.id):
            continue

        has_photo, nsfw_dp = await scan_current_profile_photo(client, member.id)

        if nsfw_dp:
            await handle_nsfw_user_violation(
                client=client,
                chat_id=chat_id,
                user_id=member.id,
                reason="Profile Photo (DP)",
                message=None,
            )


# ============================================================
# HIGH SPEED 18+ STICKER AND MEDIA SCANNER (GROUP=-5)
# ============================================================

@app.on_message(
    filters.group & (filters.sticker | filters.photo | filters.animation | filters.video),
    group=-5
)
async def media_nsfw_checker(client: Client, message: Message):
    if getattr(message, "service", None) or not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    if await is_admin_or_owner(client, chat_id, user_id) or await is_user_approved(client, chat_id, user_id):
        return

    file_path = None
    media_type = "Sticker/Media"

    if message.sticker:
        media_type = "18+ Adult Sticker"
    elif message.photo:
        media_type = "Photo"
    elif message.animation:
        media_type = "GIF/Animation"
    elif message.video:
        media_type = "Video"

    try:
        # Download media/sticker
        file_path = await client.download_media(message)

        if not file_path or not os.path.exists(file_path):
            return

        # Scan with NSFW Engine
        result = await asyncio.to_thread(is_nsfw_media, file_path)

        if result is True:
            await handle_nsfw_violation(
                client,
                message,
                media_type,
            )

    except Exception as e:
        print(f"[Sticker/Media Scanner Error]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# ============================================================
# START & HELP BUTTONS
# ============================================================

def build_start_buttons(bot_username: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Add Me To Your Group ➕",
                    url=f"https://t.me/{bot_username}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton("💬 Support Group", url=Config.SUPPORT_GROUP),
                InlineKeyboardButton("📢 Update Channel", url=Config.UPDATE_CHANNEL),
            ],
            [
                InlineKeyboardButton("👑 Owner", url=f"https://t.me/{Config.OWNER_USERNAME}"),
                InlineKeyboardButton("❓ Help & Commands", callback_data="help_menu"),
            ],
        ]
    )


def build_help_buttons(bot_username: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Add Me To Your Group ➕",
                    url=f"https://t.me/{bot_username}?startgroup=true",
                )
            ],
            [InlineKeyboardButton("🔙 Back to Start", callback_data="start_menu")],
        ]
    )


# ============================================================
# COMMANDS & CALLBACKS
# ============================================================

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    try:
        bot = await client.get_me()
        user = message.from_user
        if not user:
            return

        await add_served_user(user.id)

        await message.reply_photo(
            photo=Config.START_IMG,
            caption=(
                f"👋 **Hello {user.mention}!**\n\n"
                f"🤖 Welcome to **VAMPIREGCPRO**!\n\n"
                f"🛡️ Advanced Telegram group moderation bot.\n\n"
                f"✨ **Core Features:**\n"
                f"• NSFW Profile Photo Scanning\n"
                f"• 18+ Adult Sticker & GIF Auto-Delete\n"
                f"• Adult Media Auto-Delete\n"
                f"• 3-Warning Auto-Mute"
            ),
            reply_markup=build_start_buttons(bot.username),
        )
    except Exception as e:
        print(f"[Start Command Error] {e}")


@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    try:
        bot = await client.get_me()
        await message.reply_text(
            (
                "📖 **VAMPIREGCPRO Commands & Guide**\n\n"
                "• `/start` - Start the bot\n"
                "• `/help` - Help menu\n"
                "• `/approve` - Approve a user\n"
                "• `/unapprove` - Remove approval"
            ),
            reply_markup=build_help_buttons(bot.username),
        )
    except Exception as e:
        print(f"[Help Error] {e}")


@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    try:
        await query.answer()
        bot = await client.get_me()

        if query.data == "help_menu":
            await query.message.edit_text(
                "📖 **VAMPIREGCPRO Commands & Guide**\n\n• `/start` - Start\n• `/approve` - Approve user",
                reply_markup=build_help_buttons(bot.username),
            )
        elif query.data == "start_menu":
            await query.message.edit_text(
                f"👋 **Hello {query.from_user.mention}!**\n\n🛡️ Advanced Telegram moderation bot.",
                reply_markup=build_start_buttons(bot.username),
            )
    except Exception as e:
        print(f"[Callback Error] {e}")


@app.on_message(filters.group & filters.command("approve"))
async def approve_user(client: Client, message: Message):
    if not message.from_user:
        return
    admin = await client.get_chat_member(message.chat.id, message.from_user.id)
    if admin.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return await message.reply_text("❌ Only administrators can approve users.")

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply_text("❌ Reply to a user's message to approve them.")

    target_user = message.reply_to_message.from_user
    await approve_user_db(message.chat.id, target_user.id)
    await message.reply_text(f"✅ {target_user.mention} is now approved.")


@app.on_message(filters.group & filters.command("unapprove"))
async def unapprove_user(client: Client, message: Message):
    if not message.from_user:
        return
    admin = await client.get_chat_member(message.chat.id, message.from_user.id)
    if admin.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return await message.reply_text("❌ Only administrators can unapprove users.")

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply_text("❌ Reply to a user's message to unapprove them.")

    target_user = message.reply_to_message.from_user
    await unapprove_user_db(message.chat.id, target_user.id)
    await message.reply_text(f"🚫 {target_user.mention} has been unapproved.")


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("VAMPIRE GC PRO Bot Started - Made by Vampire King")
    print("=" * 60)
    app.run()
