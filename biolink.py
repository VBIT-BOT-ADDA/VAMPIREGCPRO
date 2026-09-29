import re
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message, ChatPermissions
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

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


# ============================================================
# Helpers
# ============================================================
async def is_user_approved(chat_id: int, user_id: int) -> bool:
    """Check whether user is approved in this group."""
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
    - Bot owner
    - Group owner
    - Group administrators
    """

    if not user_id:
        return True

    # --------------------------------------------------------
    # Global Bot Owner
    # --------------------------------------------------------
    try:
        if int(user_id) == int(Config.OWNER_ID):
            return True
    except (AttributeError, TypeError, ValueError):
        pass

    # --------------------------------------------------------
    # Group Admin / Owner
    # --------------------------------------------------------
    try:
        member = await client.get_chat_member(
            chat_id,
            user_id,
        )

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


# ============================================================
# Warning System
# ============================================================
async def increment_warnings(
    chat_id: int,
    user_id: int,
) -> int:
    """
    Atomically increase warning count.

    1st violation -> 1
    2nd violation -> 2
    3rd violation -> 3
    4th violation -> 4 -> MUTE
    """

    filter_query = {
        "chat_id": int(chat_id),
        "user_id": int(user_id),
    }

    try:
        result = await warnings_db.find_one_and_update(
            filter_query,
            {
                "$inc": {
                    "count": 1,
                },
                "$set": {
                    "updated_at": time.time(),
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        if result:
            return int(result.get("count", 1))

    except Exception as e:
        print(
            f"[Warning Increment Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )

    return 1


async def reset_warnings(
    chat_id: int,
    user_id: int,
):
    """Reset warnings after successful mute."""
    try:
        await warnings_db.delete_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )

    except Exception as e:
        print(
            f"[Warning Reset Error] "
            f"{chat_id}/{user_id}: {e}"
        )


def user_has_bio_link(bio: str) -> bool:
    """Detect website / Telegram link / domain in profile bio."""

    if not bio:
        return False

    return bool(URL_REGEX.search(bio))


# ============================================================
# Bio Violation Handler
# ============================================================
async def handle_bio_violation(
    client: Client,
    message: Message,
):
    """
    Bio link violation system.

    1st message with Bio link:
        Delete + Warning 1/3

    2nd message with Bio link:
        Delete + Warning 2/3

    3rd message with Bio link:
        Delete + Warning 3/3

    4th message with Bio link:
        Delete + Mute

    If user removes the link after warning 1/2/3,
    nothing happens to normal messages.
    """

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # ========================================================
    # ADMIN / OWNER PROTECTION
    # ========================================================
    if await is_admin_or_owner(
        client,
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # APPROVED USER PROTECTION
    # ========================================================
    if await is_user_approved(
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # DELETE OFFENDING MESSAGE IMMEDIATELY
    # ========================================================
    try:
        await message.delete()

        print(
            f"[Bio Link Deleted] "
            f"chat={chat_id} user={user_id}"
        )

    except Exception as e:
        print(
            f"[BioLink Delete Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )

    # ========================================================
    # INCREMENT WARNING
    # ========================================================
    warn_count = await increment_warnings(
        chat_id,
        user_id,
    )

    user_mention = message.from_user.mention

    # ========================================================
    # WARNING 1/3
    # ========================================================
    if warn_count == 1:

        try:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"🚨 **Bio Link Warning [1/3]**\n\n"
                    f"Hey {user_mention}, a link/website was "
                    f"detected in your Telegram profile Bio.\n\n"
                    f"🗑 Your message was removed.\n"
                    f"⚠️ Please remove the link from your Bio.\n\n"
                    f"🔒 **3 warnings = mute on the next violation.**"
                ),
            )

        except Exception as e:
            print(
                f"[Warning Message Error] "
                f"{chat_id}/{user_id}: {e}"
            )

        return

    # ========================================================
    # WARNING 2/3
    # ========================================================
    if warn_count == 2:

        try:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ **Bio Link Warning [2/3]**\n\n"
                    f"{user_mention}, the link is still present "
                    f"in your Telegram profile Bio.\n\n"
                    f"🗑 Your message was removed.\n"
                    f"❗ Please remove the link from your Bio.\n\n"
                    f"🔒 **One more warning and the next violation "
                    f"will result in mute.**"
                ),
            )

        except Exception as e:
            print(
                f"[Warning Message Error] "
                f"{chat_id}/{user_id}: {e}"
            )

        return

    # ========================================================
    # WARNING 3/3
    # ========================================================
    if warn_count == 3:

        try:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"🚨 **Final Bio Link Warning [3/3]**\n\n"
                    f"{user_mention}, the link is still present "
                    f"in your Telegram profile Bio.\n\n"
                    f"🗑 Your message was removed.\n"
                    f"⚠️ This is your **final warning**.\n\n"
                    f"🔇 **If you send another message while "
                    f"the Bio link remains, you will be muted.**"
                ),
            )

        except Exception as e:
            print(
                f"[Warning Message Error] "
                f"{chat_id}/{user_id}: {e}"
            )

        return

    # ========================================================
    # 4TH VIOLATION -> MUTE
    # ========================================================
    if warn_count >= 4:

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
                    f"🚫 **User Muted**\n\n"
                    f"👤 **User:** {user_mention}\n"
                    f"📌 **Reason:** Bio link remained after "
                    f"3 warnings.\n\n"
                    f"🔇 User has been muted automatically."
                ),
            )

            print(
                f"[Bio Link Mute] "
                f"chat={chat_id} user={user_id}"
            )

            # Reset after successful mute
            await reset_warnings(
                chat_id,
                user_id,
            )

        except Exception as e:
            print(
                f"[Mute Error] "
                f"chat={chat_id}, user={user_id}: {e}"
            )

            try:
                await client.send_message(
                    chat_id=chat_id,
                    text=(
                        f"❌ **Mute failed for {user_mention}.**\n\n"
                        f"Please make sure the bot has permission "
                        f"to restrict/mute members."
                    ),
                )

            except Exception as send_error:
                print(
                    f"[Mute Error Message] {send_error}"
                )


# ============================================================
# HIGH PRIORITY BIO SCANNER
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
    Every normal group message checks the user's
    CURRENT Telegram Bio immediately.

    Bio link found:
        Message deleted immediately
        Warning added immediately

    No cache is used so Bio changes are detected immediately.
    """

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # ========================================================
    # ADMIN / OWNER PROTECTION
    # ========================================================
    if await is_admin_or_owner(
        client,
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # APPROVED USER PROTECTION
    # ========================================================
    if await is_user_approved(
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # GET CURRENT TELEGRAM PROFILE
    # ========================================================
    try:
        user_info = await client.get_chat(user_id)

        bio_text = (user_info.bio or "").strip()

        # ====================================================
        # CHECK LINK IMMEDIATELY
        # ====================================================
        if user_has_bio_link(bio_text):

            print(
                f"[Bio Link Detected] "
                f"chat={chat_id} user={user_id} "
                f"bio={bio_text}"
            )

            await handle_bio_violation(
                client,
                message,
            )

            return

        # ====================================================
        # NO LINK -> ALLOW MESSAGE
        # ====================================================
        return

    except Exception as e:
        print(
            f"[Bio Check Error] "
            f"chat={chat_id}, user={user_id}: {e}"
        )


# ============================================================
# APPROVE
# ============================================================
@app.on_message(
    filters.group & filters.command("approve")
)
async def approve_cmd(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    # Only Admin / Owner
    if not await is_admin_or_owner(
        client,
        message.chat.id,
        message.from_user.id,
    ):
        return await message.reply_text(
            "❌ **Admin command only.**"
        )

    # Must reply to user's message
    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ **Reply to a user's message and use /approve.**"
        )

    if not message.reply_to_message.from_user:
        return await message.reply_text(
            "❌ **User not found.**"
        )

    target_user_id = (
        message.reply_to_message.from_user.id
    )

    try:
        await approved_db.update_one(
            {
                "chat_id": int(message.chat.id),
                "user_id": int(target_user_id),
            },
            {
                "$set": {
                    "chat_id": int(message.chat.id),
                    "user_id": int(target_user_id),
                    "approved_at": time.time(),
                }
            },
            upsert=True,
        )

        # Optional: reset warning count
        await reset_warnings(
            message.chat.id,
            target_user_id,
        )

        await message.reply_text(
            "✅ **User Approved!**\n\n"
            "This user's Bio links will now be ignored "
            "in this group."
        )

    except Exception as e:
        print(
            f"[Approve Error] "
            f"{message.chat.id}/{target_user_id}: {e}"
        )


# ============================================================
# UNAPPROVE
# ============================================================
@app.on_message(
    filters.group & filters.command("unapprove")
)
async def unapprove_cmd(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    # Only Admin / Owner
    if not await is_admin_or_owner(
        client,
        message.chat.id,
        message.from_user.id,
    ):
        return await message.reply_text(
            "❌ **Admin command only.**"
        )

    # Must reply to user's message
    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ **Reply to a user's message and use /unapprove.**"
        )

    if not message.reply_to_message.from_user:
        return await message.reply_text(
            "❌ **User not found.**"
        )

    target_user_id = (
        message.reply_to_message.from_user.id
    )

    try:
        await approved_db.delete_one(
            {
                "chat_id": int(message.chat.id),
                "user_id": int(target_user_id),
            }
        )

        await message.reply_text(
            "🚫 **User Unapproved!**\n\n"
            "Bio link checking has been enabled "
            "for this user again."
        )

    except Exception as e:
        print(
            f"[Unapprove Error] "
            f"{message.chat.id}/{target_user_id}: {e}"
        )
