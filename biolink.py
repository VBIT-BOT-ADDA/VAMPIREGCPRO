import re
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message, ChatPermissions
from motor.motor_asyncio import AsyncIOMotorClient

from config import Config


# ============================================================
# Main App
# ============================================================
try:
    from VampirePro import app
except ImportError:
    from bot import app


# ============================================================
# Database Setup
# ============================================================
mongo_client = AsyncIOMotorClient(Config.MONGO_DB_URI)
db = mongo_client["VAMPIREGCPRO_DB"]

approved_db = db["approved_users"]
warnings_db = db["warnings"]


# ============================================================
# Bio Link Detection
# ============================================================
URL_REGEX = re.compile(
    r"""
    (?:
        https?://\S+
        |
        www\.\S+
        |
        t\.me/\S+
        |
        telegram\.me/\S+
        |
        \b[a-zA-Z0-9.-]+\.
        (?:com|org|net|me|in|site|xyz|online|app|io|co|dev|gg|ly)
        (?:/\S*)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Cache key = (chat_id, user_id)
# This prevents one group's cached result from affecting another group.
BIO_CACHE = {}
CACHE_TTL = 60  # seconds


# ============================================================
# Helpers
# ============================================================
async def is_user_approved(chat_id: int, user_id: int) -> bool:
    """Return True if this user is approved/whitelisted in this group."""
    try:
        result = await approved_db.find_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )
        return bool(result)
    except Exception as e:
        print(f"[Approved Check Error] {chat_id}/{user_id}: {e}")
        return False


async def is_admin_or_owner(
    client: Client,
    chat_id: int,
    user_id: int,
) -> bool:
    """
    Protect:
    1. Configured bot owner (Config.OWNER_ID)
    2. Telegram group owner
    3. Telegram group administrators
    """
    if not user_id:
        return True

    # Global bot owner protection
    try:
        if int(user_id) == int(Config.OWNER_ID):
            return True
    except (AttributeError, TypeError, ValueError):
        pass

    # Group admin/owner protection
    try:
        member = await client.get_chat_member(chat_id, user_id)

        if member.status in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        ):
            return True

    except Exception as e:
        print(
            f"[Admin Check Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )

    return False


async def increment_warnings(chat_id: int, user_id: int) -> int:
    """Increment warning count for a user in a specific group."""
    filter_query = {
        "chat_id": int(chat_id),
        "user_id": int(user_id),
    }

    try:
        doc = await warnings_db.find_one(filter_query)
        current = int(doc.get("count", 0)) if doc else 0
    except Exception:
        current = 0

    new_count = current + 1

    await warnings_db.update_one(
        filter_query,
        {
            "$set": {
                "count": new_count,
                "updated_at": time.time(),
            }
        },
        upsert=True,
    )

    return new_count


async def reset_warnings(chat_id: int, user_id: int):
    """Reset warnings after a successful mute."""
    try:
        await warnings_db.delete_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )
    except Exception as e:
        print(f"[Warning Reset Error] {chat_id}/{user_id}: {e}")


def user_has_bio_link(bio: str) -> bool:
    """Return True when a Telegram profile bio contains a detectable link/domain."""
    if not bio:
        return False

    return bool(URL_REGEX.search(bio))


# ============================================================
# Bio Violation Handler
# ============================================================
async def handle_bio_violation(client: Client, message: Message):
    """
    Delete a normal user's message and issue a warning.

    Admins, group owner and configured bot owner are NEVER deleted,
    warned or muted by this handler.
    """
    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # --------------------------------------------------------
    # HARD ADMIN/OWNER PROTECTION
    # --------------------------------------------------------
    if await is_admin_or_owner(client, chat_id, user_id):
        return

    # Approved users are also ignored
    if await is_user_approved(chat_id, user_id):
        return

    # --------------------------------------------------------
    # Delete offending message
    # --------------------------------------------------------
    try:
        await message.delete()
    except Exception as e:
        print(
            f"[BioLink Delete Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )

    user_mention = message.from_user.mention

    # --------------------------------------------------------
    # Add warning
    # --------------------------------------------------------
    try:
        warn_count = await increment_warnings(chat_id, user_id)
    except Exception as e:
        print(
            f"[Warning Increment Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )
        return

    # --------------------------------------------------------
    # Warning 1/3 or 2/3
    # --------------------------------------------------------
    if warn_count < 3:
        try:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"🚨 **Bio Link Warning [{warn_count}/3]**\n\n"
                    f"Hey {user_mention}, links/websites in your "
                    f"Telegram profile Bio are not allowed in this group.\n\n"
                    f"🗑 Your message was removed.\n"
                    f"⚠️ Please remove the link from your Bio.\n\n"
                    f"🔒 **3 warnings = automatic mute.**"
                ),
            )
        except Exception as e:
            print(
                f"[Warning Message Error] "
                f"chat={chat_id}, user={user_id}: {e}"
            )

        return

    # --------------------------------------------------------
    # 3/3 -> MUTE
    # --------------------------------------------------------
    try:
        await client.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
        )

        await client.send_message(
            chat_id=chat_id,
            text=(
                f"🚫 **User Muted [3/3]**\n\n"
                f"👤 **User:** {user_mention}\n"
                f"📌 **Reason:** Link/website detected in "
                f"profile Bio after 3 warnings.\n\n"
                f"🔇 User has been muted automatically."
            ),
        )

        # Start fresh after the mute
        await reset_warnings(chat_id, user_id)

    except Exception as e:
        print(
            f"[Mute Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )

        try:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ **Mute failed for {user_mention}.**\n"
                    f"Please make sure the bot has permission to "
                    f"restrict/mute members."
                ),
            )
        except Exception as send_error:
            print(f"[Mute Error Message] {send_error}")


# ============================================================
# High-Priority Bio Scanner
# ============================================================
@app.on_message(
    filters.group & ~filters.me & ~filters.service,
    group=-2,
)
async def biolink_checker_handler(
    client: Client,
    message: Message,
):
    """
    Checks a sender's Telegram Bio when they send a group message.

    Normal users:
        Bio link -> message deleted -> warning
        3 warnings -> mute

    Admin/group owner/bot owner:
        Completely ignored
    """
    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # --------------------------------------------------------
    # HARD ADMIN/OWNER PROTECTION
    # --------------------------------------------------------
    if await is_admin_or_owner(client, chat_id, user_id):
        return

    # Approved users do not get checked
    if await is_user_approved(chat_id, user_id):
        return

    current_time = time.time()
    cache_key = (chat_id, user_id)

    # --------------------------------------------------------
    # Cache check
    # --------------------------------------------------------
    cached_data = BIO_CACHE.get(cache_key)

    if cached_data:
        cache_age = current_time - cached_data["time"]

        if cache_age < CACHE_TTL:
            if cached_data["has_link"]:
                await handle_bio_violation(client, message)
            return

        # Expired cache
        BIO_CACHE.pop(cache_key, None)

    # --------------------------------------------------------
    # Fetch Telegram profile
    # --------------------------------------------------------
    try:
        user_info = await client.get_chat(user_id)
        bio_text = (user_info.bio or "").strip()

        has_link = user_has_bio_link(bio_text)

        BIO_CACHE[cache_key] = {
            "has_link": has_link,
            "time": current_time,
        }

        if has_link:
            await handle_bio_violation(client, message)

    except Exception as e:
        print(
            f"[Bio Check Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )
