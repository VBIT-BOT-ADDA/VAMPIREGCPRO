import os
import asyncio
import time
import unicodedata
import re

# ============================================================
# EVENT LOOP FIX
# ============================================================

try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import requests

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

mongo_client = AsyncIOMotorClient(Config.MONGO_DB_URI)

db = mongo_client["VAMPIREGCPRO_DB"]

users_db = db["users"]
chats_db = db["chats"]
approved_db = db["approved_users"]
warnings_db = db["warnings"]


# ============================================================
# DATABASE HELPERS
# ============================================================

async def add_served_user(user_id: int):
    if not user_id:
        return

    await users_db.update_one(
        {"user_id": int(user_id)},
        {
            "$set": {
                "user_id": int(user_id),
            }
        },
        upsert=True,
    )


async def add_served_chat(chat_id: int):
    if not chat_id:
        return

    await chats_db.update_one(
        {"chat_id": int(chat_id)},
        {
            "$set": {
                "chat_id": int(chat_id),
            }
        },
        upsert=True,
    )


async def get_served_users():
    users = []

    async for doc in users_db.find({}):
        if doc.get("user_id"):
            users.append(doc["user_id"])

    return users


async def get_served_chats():
    chats = []

    async for doc in chats_db.find({}):
        if doc.get("chat_id"):
            chats.append(doc["chat_id"])

    return chats


async def is_user_approved(chat_id: int, user_id: int) -> bool:
    result = await approved_db.find_one(
        {
            "chat_id": int(chat_id),
            "user_id": int(user_id),
        }
    )

    return bool(result)


async def approve_user_db(chat_id: int, user_id: int):
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


async def unapprove_user_db(chat_id: int, user_id: int):
    await approved_db.delete_one(
        {
            "chat_id": int(chat_id),
            "user_id": int(user_id),
        }
    )


async def get_user_warnings(chat_id: int, user_id: int) -> int:
    doc = await warnings_db.find_one(
        {
            "chat_id": int(chat_id),
            "user_id": int(user_id),
        }
    )

    if not doc:
        return 0

    return int(doc.get("count", 0))


async def increment_warnings(chat_id: int, user_id: int) -> int:
    result = await warnings_db.find_one_and_update(
        {
            "chat_id": int(chat_id),
            "user_id": int(user_id),
        },
        {
            "$inc": {
                "count": 1
            }
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    return int(result.get("count", 1))


async def reset_warnings(chat_id: int, user_id: int):
    await warnings_db.delete_one(
        {
            "chat_id": int(chat_id),
            "user_id": int(user_id),
        }
    )


# ============================================================
# USER DISPLAY
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

    return name or "Unknown"


# ============================================================
# LOGGER
# ============================================================

async def send_logger_message(
    client: Client,
    text: str,
    reply_markup=None,
):
    """
    Safe logger.

    Logger failure NEVER crashes the bot.
    """

    logger_id = getattr(Config, "LOGGER_ID", None)

    if not logger_id:
        print("[Logger] LOGGER_ID is not configured.")
        return False

    try:
        logger_id = int(str(logger_id).strip())
    except (TypeError, ValueError):
        print(
            f"[Logger Error] Invalid LOGGER_ID: {logger_id}"
        )
        return False

    try:
        # First verify that Telegram can resolve the peer.
        try:
            logger_chat = await client.get_chat(logger_id)

            print(
                f"[Logger] Connected to logger chat: "
                f"{logger_chat.title or logger_chat.first_name or logger_id}"
            )

        except Exception as e:
            print(
                f"[Logger Error] Cannot access LOGGER_ID {logger_id}: {e}"
            )

            print(
                "[Logger Fix] Make sure the bot is a member/admin "
                "of the logger group and LOGGER_ID is correct."
            )

            return False

        await client.send_message(
            chat_id=logger_id,
            text=text,
            reply_markup=reply_markup,
        )

        return True

    except Exception as e:
        print(
            f"[Logger Error] Could not send logger message: {e}"
        )

        return False


# ============================================================
# ADMIN / OWNER CHECK
# ============================================================

async def is_admin_or_owner(
    client: Client,
    chat_id: int,
    user_id: int,
) -> bool:

    if not user_id:
        return True

    # Config owner
    try:
        owner_id = int(Config.OWNER_ID)

        if int(user_id) == owner_id:
            return True

    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        pass

    try:
        member = await client.get_chat_member(
            chat_id,
            user_id,
        )

        if member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            return True

    except Exception as e:
        print(
            f"[Admin Check] Failed for "
            f"{user_id} in {chat_id}: {e}"
        )

    return False


# ============================================================
# NSFW SIGHTENGINE
# ============================================================

def is_nsfw_media(file_path: str) -> bool:

    api_user = getattr(
        Config,
        "SIGHTENGINE_API_USER",
        None,
    )

    api_secret = getattr(
        Config,
        "SIGHTENGINE_API_SECRET",
        None,
    )

    if not api_user or not api_secret:
        print(
            "[NSFW Scanner] Sightengine credentials missing."
        )
        return False

    if not file_path or not os.path.exists(file_path):
        return False

    url = "https://api.sightengine.com/1.0/check.json"

    params = {
        "models": "nudity-2.0",
        "api_user": api_user,
        "api_secret": api_secret,
    }

    try:
        with open(file_path, "rb") as image_file:

            response = requests.post(
                url,
                files={
                    "media": image_file
                },
                data=params,
                timeout=20,
            )

        response.raise_for_status()

        data = response.json()

        if data.get("status") != "success":

            print(
                "[NSFW Scanner] "
                f"API failed: {data}"
            )

            return False

        nudity = data.get(
            "nudity",
            {},
        )

        sexual_activity = float(
            nudity.get(
                "sexual_activity",
                0,
            ) or 0
        )

        sexual_display = float(
            nudity.get(
                "sexual_display",
                0,
            ) or 0
        )

        erotica = float(
            nudity.get(
                "erotica",
                0,
            ) or 0
        )

        suggestive = float(
            nudity.get(
                "suggestive",
                0,
            ) or 0
        )

        score = max(
            sexual_activity,
            sexual_display,
            erotica,
            suggestive,
        )

        print(
            f"[NSFW Scanner] "
            f"score={score:.3f} "
            f"file={file_path}"
        )

        # Your current threshold
        return score > 0.5

    except Exception as e:

        print(
            f"[NSFW Scanner Error] {e}"
        )

        return False


# ============================================================
# GET USER MENTION
# ============================================================

async def get_user_mention(
    client: Client,
    user_id: int,
):

    try:
        user = await client.get_users(user_id)

        return user.mention

    except Exception:

        return f"`{user_id}`"


# ============================================================
# NSFW VIOLATION
# ============================================================

async def handle_nsfw_violation(
    client: Client,
    message: Message,
    reason: str,
):

    if not message.from_user:
        return

    await handle_nsfw_user_violation(
        client=client,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        reason=reason,
        message=message,
    )


async def handle_nsfw_user_violation(
    client: Client,
    chat_id: int,
    user_id: int,
    reason: str,
    message: Message = None,
):

    if not user_id:
        return False

    # --------------------------------------------------------
    # ADMIN / OWNER PROTECTION
    # --------------------------------------------------------

    if await is_admin_or_owner(
        client,
        chat_id,
        user_id,
    ):

        print(
            f"[NSFW] Admin/Owner skipped: "
            f"{user_id}"
        )

        return False

    # --------------------------------------------------------
    # APPROVED USER
    # --------------------------------------------------------

    if await is_user_approved(
        chat_id,
        user_id,
    ):

        print(
            f"[NSFW] Approved user skipped: "
            f"{user_id}"
        )

        return False

    # --------------------------------------------------------
    # DELETE OFFENDING MESSAGE
    # --------------------------------------------------------

    if message is not None:

        try:

            await message.delete()

            print(
                f"[NSFW] Message deleted from "
                f"{user_id}"
            )

        except Exception as e:

            print(
                f"[NSFW Delete Error] {e}"
            )

    # --------------------------------------------------------
    # USER MENTION
    # --------------------------------------------------------

    user_mention = await get_user_mention(
        client,
        user_id,
    )

    # --------------------------------------------------------
    # WARNING
    # --------------------------------------------------------

    warn_count = await increment_warnings(
        chat_id,
        user_id,
    )

    print(
        f"[NSFW] Warning "
        f"{warn_count}/3 for "
        f"{user_id} | {reason}"
    )

    # --------------------------------------------------------
    # WARNING 1 / 2
    # --------------------------------------------------------

    if warn_count < 3:

        try:

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"🚨 **NSFW Warning "
                    f"[{warn_count}/3]**\n\n"
                    f"Hey {user_mention}, your "
                    f"**{reason}** contains "
                    f"adult/NSFW content and "
                    f"was removed.\n\n"
                    f"Please follow the group rules.\n"
                    f"3 warnings will result in "
                    f"an automatic **Mute**."
                ),
            )

        except Exception as e:

            print(
                f"[Warning Message Error] {e}"
            )

        return True

    # --------------------------------------------------------
    # 3 WARNINGS -> MUTE
    # --------------------------------------------------------

    try:

        await client.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
        )

        print(
            f"[NSFW] User muted: "
            f"{user_id}"
        )

        await client.send_message(
            chat_id=chat_id,
            text=(
                f"🚫 **User Muted**\n\n"
                f"**User:** {user_mention}\n"
                f"**Reason:** Reached 3/3 "
                f"NSFW warnings."
            ),
        )

        await reset_warnings(
            chat_id,
            user_id,
        )

        return True

    except Exception as e:

        print(
            f"[Mute Error] "
            f"Could not mute {user_id}: {e}"
        )

        try:

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ **Mute failed**\n\n"
                    f"User: {user_mention}\n"
                    f"Reason: `{e}`"
                ),
            )

        except Exception:
            pass

        return False


# ============================================================
# START BUTTONS
# ============================================================

def build_start_buttons(
    bot_username: str,
):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Add Me To Your Group ➕",
                    url=(
                        f"https://t.me/"
                        f"{bot_username}"
                        f"?startgroup=true"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "💬 Support Group",
                    url=Config.SUPPORT_GROUP,
                ),
                InlineKeyboardButton(
                    "📢 Update Channel",
                    url=Config.UPDATE_CHANNEL,
                ),
            ],
            [
                InlineKeyboardButton(
                    "👑 Owner",
                    url=(
                        f"https://t.me/"
                        f"{Config.OWNER_USERNAME}"
                    ),
                ),
                InlineKeyboardButton(
                    "❓ Help & Commands",
                    callback_data="help_menu",
                ),
            ],
        ]
    )


def build_help_buttons(
    bot_username: str,
):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Add Me To Your Group ➕",
                    url=(
                        f"https://t.me/"
                        f"{bot_username}"
                        f"?startgroup=true"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back to Start",
                    callback_data="start_menu",
                )
            ],
        ]
    )


# ============================================================
# /START
# LOGGER = USER NAME + USERNAME + ID
# ============================================================

@app.on_message(
    filters.command("start")
    & filters.private
)
async def start_command(
    client: Client,
    message: Message,
):

    try:

        bot = await client.get_me()

        user = message.from_user

        if not user:
            return

        await add_served_user(
            user.id
        )

        full_name = get_user_full_name(
            user
        )

        username = get_user_username(
            user
        )

        # ----------------------------------------------------
        # LOGGER
        # ----------------------------------------------------

        logger_text = (
            "🟢 **BOT STARTED**\n\n"
            f"👤 **Name:** {full_name}\n"
            f"🔗 **Username:** {username}\n"
            f"🆔 **User ID:** `{user.id}`\n"
        )

        await send_logger_message(
            client,
            logger_text,
        )

        # ----------------------------------------------------
        # USER START MESSAGE
        # ----------------------------------------------------

        await message.reply_photo(
            photo=Config.START_IMG,
            caption=(
                f"👋 **Hello {user.mention}!**\n\n"
                f"🤖 Welcome to **VAMPIREGCPRO**!\n\n"
                f"🛡️ Advanced Telegram "
                f"group moderation bot.\n\n"
                f"✨ **Core Features:**\n"
                f"• NSFW Profile Photo Scanning\n"
                f"• Adult Media Auto-Delete\n"
                f"• 3-Warning Auto-Mute\n"
                f"• Group Moderation\n"
                f"• Spam Protection"
            ),
            reply_markup=build_start_buttons(
                bot.username
            ),
        )

    except Exception as e:

        print(
            f"[Start Command Error] {e}"
        )


# ============================================================
# HELP
# ============================================================

@app.on_message(
    filters.command("help")
    & filters.private
)
async def help_command(
    client: Client,
    message: Message,
):

    try:

        bot = await client.get_me()

        await message.reply_text(
            (
                "📖 **VAMPIREGCPRO "
                "Commands & Guide**\n\n"
                "• `/start` - Start the bot\n"
                "• `/help` - Help menu\n"
                "• `/approve` - Approve a user\n"
                "• `/unapprove` - Remove approval\n\n"
                "👑 **Owner:**\n"
                "• `/broadcast <msg>`\n"
                "• `/broadcast -user <msg>`\n"
                "• `/broadcast -user -pin <msg>`"
            ),
            reply_markup=build_help_buttons(
                bot.username
            ),
        )

    except Exception as e:

        print(
            f"[Help Error] {e}"
        )


# ============================================================
# CALLBACK
# ============================================================

@app.on_callback_query()
async def callback_handler(
    client: Client,
    query: CallbackQuery,
):

    try:

        bot = await client.get_me()

        if query.data == "help_menu":

            await query.message.edit_text(
                (
                    "📖 **VAMPIREGCPRO "
                    "Commands & Guide**\n\n"
                    "• `/start` - Start the bot\n"
                    "• `/help` - Help menu\n"
                    "• `/approve` - Approve user\n"
                    "• `/unapprove` - Unapprove user"
                ),
                reply_markup=build_help_buttons(
                    bot.username
                ),
            )

        elif query.data == "start_menu":

            await query.message.edit_text(
                (
                    f"👋 **Hello "
                    f"{query.from_user.mention}!**\n\n"
                    f"🤖 Welcome to "
                    f"**VAMPIREGCPRO**!\n\n"
                    f"🛡️ Advanced Telegram "
                    f"group moderation bot."
                ),
                reply_markup=build_start_buttons(
                    bot.username
                ),
            )

    except Exception as e:

        print(
            f"[Callback Error] {e}"
        )


# ============================================================
# NEW MEMBER / BOT ADDED
# ============================================================

@app.on_message(
    filters.new_chat_members
)
async def new_chat_event(
    client: Client,
    message: Message,
):

    chat_id = message.chat.id

    await add_served_chat(
        chat_id
    )

    try:

        bot = await client.get_me()

    except Exception as e:

        print(
            f"[Bot Info Error] {e}"
        )

        return

    for member in message.new_chat_members:

        # ====================================================
        # BOT ADDED TO GROUP
        # ====================================================

        if member.id == bot.id:

            print(
                f"[Group Join] Bot added to: "
                f"{message.chat.title}"
            )

            # ------------------------------------------------
            # GROUP MEMBERS COUNT
            # ------------------------------------------------

            try:

                members_count = (
                    await client.get_chat_members_count(
                        chat_id
                    )
                )

            except Exception as e:

                print(
                    f"[Members Count Error] {e}"
                )

                members_count = "Unknown"

            # ------------------------------------------------
            # WHO ADDED THE BOT
            # ------------------------------------------------

            adder = message.from_user

            if adder:

                adder_name = get_user_full_name(
                    adder
                )

                adder_username = get_user_username(
                    adder
                )

                adder_id = adder.id

            else:

                adder_name = "Unknown"
                adder_username = "None"
                adder_id = "Unknown"

            # ------------------------------------------------
            # GROUP INVITE LINK
            # ------------------------------------------------

            invite_url = None

            try:

                expire_time = (
                    int(time.time()) + 1800
                )

                invite = (
                    await client.create_chat_invite_link(
                        chat_id=chat_id,
                        expire_date=expire_time,
                        member_limit=1,
                    )
                )

                invite_url = invite.invite_link

            except Exception as e:

                print(
                    f"[Invite Link Error] {e}"
                )

            keyboard = None

            if invite_url:

                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔗 Temporary Group Link",
                                url=invite_url,
                            )
                        ]
                    ]
                )

            # ------------------------------------------------
            # LOGGER GROUP MESSAGE
            # ------------------------------------------------

            logger_text = (
                "🏰 **BOT ADDED TO GROUP**\n\n"
                f"👥 **Group Name:** "
                f"{message.chat.title or 'Unknown'}\n"
                f"🆔 **Group ID:** `{chat_id}`\n"
                f"👤 **Members:** `{members_count}`\n\n"
                f"➕ **Added By:**\n"
                f"• **Name:** {adder_name}\n"
                f"• **Username:** {adder_username}\n"
                f"• **User ID:** `{adder_id}`"
            )

            await send_logger_message(
                client,
                logger_text,
                reply_markup=keyboard,
            )

            # Do not scan the bot itself.
            continue

        # ====================================================
        # NORMAL NEW MEMBER
        # ====================================================

        await add_served_user(
            member.id
        )

        print(
            f"[DP Scanner] New member joined: "
            f"{member.id} "
            f"({member.first_name})"
        )

        # ----------------------------------------------------
        # ADMIN / OWNER SKIP
        # ----------------------------------------------------

        if await is_admin_or_owner(
            client,
            chat_id,
            member.id,
        ):

            print(
                f"[DP Scanner] "
                f"Admin/Owner skipped: "
                f"{member.id}"
            )

            try:

                await message.reply_text(
                    f"🎉 Welcome "
                    f"{member.mention} "
                    f"to **{message.chat.title}**!"
                )

            except Exception as e:

                print(
                    f"[Welcome Error] {e}"
                )

            continue

        # ----------------------------------------------------
        # APPROVED USER
        # ----------------------------------------------------

        if await is_user_approved(
            chat_id,
            member.id,
        ):

            print(
                f"[DP Scanner] "
                f"Approved user skipped: "
                f"{member.id}"
            )

            try:

                await message.reply_text(
                    f"🎉 Welcome "
                    f"{member.mention} "
                    f"to **{message.chat.title}**!"
                )

            except Exception as e:

                print(
                    f"[Welcome Error] {e}"
                )

            continue

        # ----------------------------------------------------
        # DP SCAN
        # ----------------------------------------------------

        dp_found = False
        nsfw_dp = False

        try:

            async for photo in client.get_chat_photos(
                member.id,
                limit=1,
            ):

                dp_found = True

                dp_path = None

                try:

                    dp_path = await client.download_media(
                        photo.file_id
                    )

                    if (
                        not dp_path
                        or not os.path.exists(dp_path)
                    ):

                        print(
                            f"[DP Scanner] "
                            f"DP download failed "
                            f"for {member.id}"
                        )

                        break

                    print(
                        f"[DP Scanner] "
                        f"Downloaded DP for "
                        f"{member.id}: "
                        f"{dp_path}"
                    )

                    # ----------------------------------------
                    # SIGHTENGINE
                    # ----------------------------------------

                    nsfw_dp = is_nsfw_media(
                        dp_path
                    )

                    if nsfw_dp:

                        print(
                            f"[DP Scanner] "
                            f"NSFW DP detected "
                            f"for user "
                            f"{member.id}"
                        )

                        # ------------------------------------
                        # IMMEDIATE WARNING
                        # ------------------------------------

                        await handle_nsfw_user_violation(
                            client=client,
                            chat_id=chat_id,
                            user_id=member.id,
                            reason="Profile Photo (DP)",
                        )

                        # IMPORTANT:
                        # Telegram Bot API cannot delete the
                        # user's actual profile photo.
                        #
                        # Therefore we DO NOT send the normal
                        # welcome message after an NSFW DP.

                    else:

                        print(
                            f"[DP Scanner] "
                            f"DP is OK for "
                            f"{member.id}"
                        )

                except Exception as e:

                    print(
                        f"[DP Scanner] "
                        f"Error checking "
                        f"{member.id}: {e}"
                    )

                finally:

                    if (
                        dp_path
                        and os.path.exists(dp_path)
                    ):

                        try:

                            os.remove(
                                dp_path
                            )

                        except Exception as e:

                            print(
                                f"[DP Scanner] "
                                f"Cleanup error: {e}"
                            )

                # Only latest/current DP.
                break

            if not dp_found:

                print(
                    f"[DP Scanner] "
                    f"No accessible DP "
                    f"for {member.id}"
                )

        except Exception as e:

            print(
                f"[DP Scanner] "
                f"get_chat_photos failed "
                f"for {member.id}: {e}"
            )

        # ----------------------------------------------------
        # WELCOME ONLY IF DP IS CLEAN
        # ----------------------------------------------------

        if not nsfw_dp:

            try:

                await message.reply_text(
                    f"🎉 Welcome "
                    f"{member.mention} "
                    f"to **{message.chat.title}**!"
                )

            except Exception as e:

                print(
                    f"[Welcome Error] {e}"
                )


# ============================================================
# GROUP MEDIA NSFW SCANNER
# ============================================================

@app.on_message(
    filters.group
    & (
        filters.sticker
        | filters.animation
        | filters.photo
    )
)
async def media_nsfw_checker(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # --------------------------------------------------------
    # ADMIN / OWNER
    # --------------------------------------------------------

    if await is_admin_or_owner(
        client,
        chat_id,
        user_id,
    ):
        return

    # --------------------------------------------------------
    # APPROVED
    # --------------------------------------------------------

    if await is_user_approved(
        chat_id,
        user_id,
    ):
        return

    # --------------------------------------------------------
    # ANIMATED / VIDEO STICKER
    # --------------------------------------------------------

    if message.sticker:

        if (
            message.sticker.is_video
            or message.sticker.is_animated
        ):

            await handle_nsfw_violation(
                client,
                message,
                "Video/Animated Sticker",
            )

            return

    file_path = None

    if message.photo:

        media_type = "Photo"

    elif message.sticker:

        media_type = "Sticker"

    else:

        media_type = "GIF"

    try:

        file_path = await client.download_media(
            message
        )

        if (
            file_path
            and os.path.exists(file_path)
        ):

            if is_nsfw_media(
                file_path
            ):

                await handle_nsfw_violation(
                    client,
                    message,
                    media_type,
                )

    except Exception as e:

        print(
            f"[Media Scanner Error] {e}"
        )

    finally:

        if (
            file_path
            and os.path.exists(file_path)
        ):

            try:

                os.remove(
                    file_path
                )

            except Exception:
                pass


# ============================================================
# APPROVE
# ============================================================

@app.on_message(
    filters.group
    & filters.command("approve")
)
async def approve_user(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    try:

        admin = await client.get_chat_member(
            message.chat.id,
            message.from_user.id,
        )

        if admin.status not in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):

            await message.reply_text(
                "❌ Only administrators can approve users."
            )

            return

    except Exception as e:

        print(
            f"[Approve Admin Check Error] {e}"
        )

        return

    if not message.reply_to_message:

        await message.reply_text(
            "❌ Reply to a user's message to approve them."
        )

        return

    target_user = (
        message.reply_to_message.from_user
    )

    if not target_user:
        return

    chat_id = message.chat.id

    await approve_user_db(
        chat_id,
        target_user.id,
    )

    await message.reply_text(
        f"✅ {target_user.mention} "
        f"is now approved.\n\n"
        f"Bot will ignore their NSFW content."
    )


# ============================================================
# UNAPPROVE
# ============================================================

@app.on_message(
    filters.group
    & filters.command("unapprove")
)
async def unapprove_user(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    try:

        admin = await client.get_chat_member(
            message.chat.id,
            message.from_user.id,
        )

        if admin.status not in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):

            await message.reply_text(
                "❌ Only administrators can unapprove users."
            )

            return

    except Exception as e:

        print(
            f"[Unapprove Admin Check Error] {e}"
        )

        return

    if not message.reply_to_message:

        await message.reply_text(
            "❌ Reply to a user's message to unapprove them."
        )

        return

    target_user = (
        message.reply_to_message.from_user
    )

    if not target_user:
        return

    await unapprove_user_db(
        message.chat.id,
        target_user.id,
    )

    await message.reply_text(
        f"🚫 {target_user.mention} "
        f"has been unapproved."
    )


# ============================================================
# BROADCAST
# ============================================================

@app.on_message(
    filters.command("broadcast")
)
async def broadcast_handler(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    if message.from_user.id != Config.OWNER_ID:
        return

    if (
        not message.reply_to_message
        and len(message.command) < 2
    ):

        await message.reply_text(
            "❌ Provide a message or reply to a message."
        )

        return

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

        targets.extend(
            users
        )

    targets = list(
        dict.fromkeys(targets)
    )

    await message.reply_text(
        f"🚀 Starting broadcast to "
        f"`{len(targets)}` targets..."
    )

    success = 0
    failed = 0

    for target_id in targets:

        try:

            if broadcast_msg:

                sent = await broadcast_msg.copy(
                    chat_id=target_id
                )

            else:

                text_to_send = " ".join(
                    word
                    for word in args[1:]
                    if word not in (
                        "-user",
                        "-pin",
                    )
                )

                sent = await client.send_message(
                    chat_id=target_id,
                    text=text_to_send,
                )

            if should_pin and sent:

                try:

                    await sent.pin(
                        disable_notification=False
                    )

                except Exception:
                    pass

            success += 1

            await asyncio.sleep(
                0.3
            )

        except Exception as e:

            failed += 1

            print(
                f"[Broadcast Error] "
                f"{target_id}: {e}"
            )

    await message.reply_text(
        (
            "✅ **Broadcast Completed!**\n\n"
            f"• Success: `{success}`\n"
            f"• Failed: `{failed}`"
        )
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print(
        "VAMPIRE GC PRO Bot Started "
        "Made by Vampire King"
    )
    print("=" * 60)

    app.run()
