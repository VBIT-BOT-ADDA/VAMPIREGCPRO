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
#
# key:
#     user_id
#
# value:
#     {
#         "file_id": "...",
#         "is_nsfw": True/False,
#         "time": timestamp
#     }
#
# अगर user DP बदलता है तो file_id भी बदलता है,
# इसलिए नई DP automatically दोबारा scan होगी.
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

            PROFILE_SCAN_CACHE.pop(
                key,
                None,
            )

    except Exception as e:

        print(
            f"[Profile Cache Cleanup Error] {e}"
        )


# ============================================================
# DATABASE HELPERS
# ============================================================

async def add_served_user(user_id: int):

    if not user_id:
        return

    try:

        await users_db.update_one(
            {
                "user_id": int(user_id)
            },
            {
                "$set": {
                    "user_id": int(user_id),
                }
            },
            upsert=True,
        )

    except Exception as e:

        print(
            f"[Served User DB Error] {e}"
        )


async def add_served_chat(chat_id: int):

    if not chat_id:
        return

    try:

        await chats_db.update_one(
            {
                "chat_id": int(chat_id)
            },
            {
                "$set": {
                    "chat_id": int(chat_id),
                }
            },
            upsert=True,
        )

    except Exception as e:

        print(
            f"[Served Chat DB Error] {e}"
        )


async def get_served_users():

    users = []

    try:

        async for doc in users_db.find({}):

            if doc.get("user_id"):

                users.append(
                    int(doc["user_id"])
                )

    except Exception as e:

        print(
            f"[Get Served Users Error] {e}"
        )

    return users


async def get_served_chats():

    chats = []

    try:

        async for doc in chats_db.find({}):

            if doc.get("chat_id"):

                chats.append(
                    int(doc["chat_id"])
                )

    except Exception as e:

        print(
            f"[Get Served Chats Error] {e}"
        )

    return chats


async def is_user_approved(
    chat_id: int,
    user_id: int,
) -> bool:

    try:

        result = await approved_db.find_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )

        return bool(result)

    except Exception as e:

        print(
            f"[Approved Check Error] {e}"
        )

        return False


async def approve_user_db(
    chat_id: int,
    user_id: int,
):

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

        print(
            f"[Approve DB Error] {e}"
        )


async def unapprove_user_db(
    chat_id: int,
    user_id: int,
):

    try:

        await approved_db.delete_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )

    except Exception as e:

        print(
            f"[Unapprove DB Error] {e}"
        )


async def get_user_warnings(
    chat_id: int,
    user_id: int,
) -> int:

    try:

        doc = await warnings_db.find_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )

        if not doc:
            return 0

        return int(
            doc.get(
                "count",
                0,
            )
        )

    except Exception as e:

        print(
            f"[Warning Read Error] {e}"
        )

        return 0


async def increment_warnings(
    chat_id: int,
    user_id: int,
) -> int:

    """
    Atomic warning increment.
    Concurrent messages भी warning count overwrite नहीं करेंगे.
    """

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

    if not result:
        return 1

    return int(
        result.get(
            "count",
            1,
        )
    )


async def reset_warnings(
    chat_id: int,
    user_id: int,
):

    try:

        await warnings_db.delete_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            }
        )

    except Exception as e:

        print(
            f"[Warning Reset Error] {e}"
        )


# ============================================================
# USER DISPLAY
# ============================================================

def get_user_username(user):

    if not user:
        return "None"

    if user.username:

        return (
            f"@{user.username}"
        )

    return "None"


def get_user_full_name(user):

    if not user:
        return "Unknown"

    first = user.first_name or ""
    last = user.last_name or ""

    name = (
        f"{first} {last}"
        .strip()
    )

    return (
        name
        if name
        else "Unknown"
    )


# ============================================================
# CONFIG OWNER ID
# ============================================================

def get_owner_id():

    try:

        return int(
            str(
                getattr(
                    Config,
                    "OWNER_ID",
                    0,
                )
            ).strip()
        )

    except Exception:

        return 0


# ============================================================
# LOGGER
# ============================================================

async def send_logger_message(
    client: Client,
    text: str,
    reply_markup=None,
):

    logger_id = getattr(
        Config,
        "LOGGER_ID",
        None,
    )

    if not logger_id:

        print(
            "[Logger] LOGGER_ID is not configured."
        )

        return False

    try:

        logger_id = int(
            str(logger_id).strip()
        )

    except (
        TypeError,
        ValueError,
    ):

        print(
            f"[Logger Error] Invalid LOGGER_ID: "
            f"{logger_id}"
        )

        return False

    try:

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

    # --------------------------------------------------------
    # CONFIG OWNER
    # --------------------------------------------------------

    try:

        owner_id = get_owner_id()

        if (
            owner_id
            and int(user_id) == owner_id
        ):

            return True

    except Exception:

        pass

    # --------------------------------------------------------
    # GROUP ADMIN / OWNER
    # --------------------------------------------------------

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
# SIGHTENGINE NSFW SCANNER
# ============================================================

def is_nsfw_media(
    file_path: str,
):

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

        return None

    if (
        not file_path
        or not os.path.exists(file_path)
    ):

        print(
            "[NSFW Scanner] File does not exist."
        )

        return None

    url = (
        "https://api.sightengine.com/"
        "1.0/check.json"
    )

    params = {
        "models": "nudity-2.0",
        "api_user": api_user,
        "api_secret": api_secret,
    }

    try:

        with open(
            file_path,
            "rb",
        ) as image_file:

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
                "[NSFW Scanner] API failed: "
                f"{data}"
            )

            return None

        nudity = data.get(
            "nudity",
            {},
        )

        sexual_activity = float(
            nudity.get(
                "sexual_activity",
                0,
            )
            or 0
        )

        sexual_display = float(
            nudity.get(
                "sexual_display",
                0,
            )
            or 0
        )

        erotica = float(
            nudity.get(
                "erotica",
                0,
            )
            or 0
        )

        suggestive = float(
            nudity.get(
                "suggestive",
                0,
            )
            or 0
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

        return score > 0.5

    except Exception as e:

        print(
            f"[NSFW Scanner Error] {e}"
        )

        return None


# ============================================================
# GET USER MENTION
# ============================================================

async def get_user_mention(
    client: Client,
    user_id: int,
):

    try:

        user = await client.get_users(
            user_id
        )

        return user.mention

    except Exception:

        return f"`{user_id}`"


# ============================================================
# SEND NSFW WARNING
# ============================================================

async def send_nsfw_warning(
    client: Client,
    chat_id: int,
    user_id: int,
    reason: str,
    warn_count: int,
):

    user_mention = await get_user_mention(
        client,
        user_id,
    )

    try:

        await client.send_message(
            chat_id=chat_id,
            text=(
                f"🚨 **NSFW Warning "
                f"[{warn_count}/3]**\n\n"
                f"Hey {user_mention}, your "
                f"**{reason}** contains "
                f"adult/NSFW content and "
                f"was detected and removed.\n\n"
                f"Please follow the group rules.\n"
                f"3 warnings will result in "
                f"an automatic **Mute**."
            ),
        )

        print(
            f"[NSFW Warning] "
            f"{warn_count}/3 -> {user_id}"
        )

        return True

    except Exception as e:

        print(
            f"[NSFW Warning Error] "
            f"{user_id}: {e}"
        )

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

    # ========================================================
    # ADMIN / OWNER PROTECTION
    # ========================================================

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

    # ========================================================
    # APPROVED USER
    # ========================================================

    if await is_user_approved(
        chat_id,
        user_id,
    ):

        print(
            f"[NSFW] Approved user skipped: "
            f"{user_id}"
        )

        return False

    # ========================================================
    # DELETE TRIGGERING MESSAGE
    # ========================================================

    if message is not None:

        try:

            await message.delete()

            print(
                f"[NSFW] Triggering message "
                f"deleted from {user_id}"
            )

        except Exception as e:

            print(
                f"[NSFW Delete Error] "
                f"{user_id}: {e}"
            )

    # ========================================================
    # INCREMENT WARNING
    # ========================================================

    try:

        warn_count = await increment_warnings(
            chat_id,
            user_id,
        )

    except Exception as e:

        print(
            f"[Warning DB Error] "
            f"{user_id}: {e}"
        )

        return False

    print(
        f"[NSFW] Warning "
        f"{warn_count}/3 | "
        f"user={user_id} | "
        f"reason={reason}"
    )

    # ========================================================
    # WARNING 1 / 2
    # ========================================================

    if warn_count < 3:

        await send_nsfw_warning(
            client=client,
            chat_id=chat_id,
            user_id=user_id,
            reason=reason,
            warn_count=warn_count,
        )

        return True

    # ========================================================
    # WARNING 3 -> MUTE
    # ========================================================

    user_mention = await get_user_mention(
        client,
        user_id,
    )

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

        try:

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"🚫 **User Muted**\n\n"
                    f"**User:** {user_mention}\n"
                    f"**Reason:** Reached "
                    f"3/3 NSFW warnings."
                ),
            )

        except Exception as e:

            print(
                f"[Mute Message Error] {e}"
            )

        # Reset after successful mute
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
                    f"⚠️ **Mute Failed**\n\n"
                    f"**User:** {user_mention}\n"
                    f"**Reason:** 3/3 warnings reached."
                ),
            )

        except Exception:
            pass

        # Keep 3 warnings in DB because mute failed
        return False


# ============================================================
# NSFW MESSAGE HANDLER
# ============================================================

async def handle_nsfw_violation(
    client: Client,
    message: Message,
    reason: str,
):

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
# CURRENT PROFILE PHOTO
# ============================================================

async def get_current_profile_photo(
    client: Client,
    user_id: int,
):

    try:

        user = await client.get_users(
            user_id
        )

        if not user:
            return None

        if not user.photo:
            return None

        file_id = (
            getattr(
                user.photo,
                "big_file_id",
                None,
            )
            or getattr(
                user.photo,
                "small_file_id",
                None,
            )
        )

        return file_id

    except Exception as e:

        print(
            f"[DP Scanner] "
            f"Could not get profile photo "
            f"for {user_id}: {e}"
        )

        return None


# ============================================================
# SCAN CURRENT PROFILE PHOTO
# ============================================================

async def scan_current_profile_photo(
    client: Client,
    user_id: int,
):

    lock = get_profile_lock(
        user_id
    )

    async with lock:

        file_id = await get_current_profile_photo(
            client,
            user_id,
        )

        # No DP
        if not file_id:

            return False, False

        cache = PROFILE_SCAN_CACHE.get(
            user_id
        )

        # ----------------------------------------------------
        # USE CACHE IF SAME DP
        # ----------------------------------------------------

        if (
            cache
            and cache.get("file_id") == file_id
        ):

            return (
                True,
                bool(
                    cache.get(
                        "is_nsfw",
                        False,
                    )
                ),
            )

        dp_path = None

        try:

            print(
                f"[DP Scanner] "
                f"Downloading current DP "
                f"for {user_id}..."
            )

            dp_path = await client.download_media(
                file_id
            )

            if (
                not dp_path
                or not os.path.exists(dp_path)
            ):

                print(
                    f"[DP Scanner] "
                    f"Download failed for {user_id}"
                )

                return True, False

            print(
                f"[DP Scanner] "
                f"Scanning DP of {user_id}..."
            )

            # requests is blocking,
            # so run it outside Pyrogram event loop.
            scan_result = await asyncio.to_thread(
                is_nsfw_media,
                dp_path,
            )

            # API failure -> don't cache
            if scan_result is None:

                print(
                    f"[DP Scanner] "
                    f"Scan failed for {user_id}"
                )

                return True, False

            nsfw = bool(
                scan_result
            )

            PROFILE_SCAN_CACHE[
                user_id
            ] = {
                "file_id": file_id,
                "is_nsfw": nsfw,
                "time": time.time(),
            }

            cleanup_profile_cache()

            if nsfw:

                print(
                    f"[DP Scanner] 🚨 "
                    f"NSFW DP DETECTED "
                    f"for {user_id}"
                )

            else:

                print(
                    f"[DP Scanner] "
                    f"DP CLEAN for {user_id}"
                )

            return True, nsfw

        except Exception as e:

            print(
                f"[DP Scanner Error] "
                f"{user_id}: {e}"
            )

            return True, False

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
                        f"[DP Cleanup Error] "
                        f"{e}"
                    )


# ============================================================
# PROFILE SCAN + MESSAGE MODERATION
# ============================================================
#
# IMPORTANT:
#
# group=-10 means this handler runs before the normal
# group handlers.
#
# Every group message from a normal user:
#
#     1. Current DP checked
#     2. If NSFW:
#            delete message
#            warning
#            3rd warning -> mute
#     3. stop_propagation()
#
# इसलिए वही message media scanner या command handler
# में दोबारा process नहीं होगा.
# ============================================================

@app.on_message(
    filters.group,
    group=-10,
)
async def profile_scan_every_message(
    client: Client,
    message: Message,
):

    # Service messages
    if getattr(
        message,
        "service",
        None,
    ):

        return

    # Sender required
    if not message.from_user:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Ignore bots
    if getattr(
        message.from_user,
        "is_bot",
        False,
    ):

        return

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
    # APPROVED USER
    # --------------------------------------------------------

    if await is_user_approved(
        chat_id,
        user_id,
    ):

        return

    # --------------------------------------------------------
    # SCAN CURRENT DP
    # --------------------------------------------------------

    has_photo, nsfw = await scan_current_profile_photo(
        client,
        user_id,
    )

    if not has_photo:

        # User has no DP.
        return

    # --------------------------------------------------------
    # NSFW DP DETECTED
    # --------------------------------------------------------

    if nsfw:

        print(
            "================================================"
        )

        print(
            f"[DP MESSAGE SCANNER] 🚨 "
            f"NSFW DP detected for {user_id}"
        )

        print(
            f"[DP MESSAGE SCANNER] "
            f"Deleting triggering message..."
        )

        print(
            "================================================"
        )

        # This message is the triggering message.
        await handle_nsfw_user_violation(
            client=client,
            chat_id=chat_id,
            user_id=user_id,
            reason="Profile Photo (DP)",
            message=message,
        )

        # IMPORTANT:
        # Do not let media/command handlers process
        # the same message again.
        try:

            message.stop_propagation()

        except Exception as e:

            print(
                f"[Propagation Stop Error] {e}"
            )

        return


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
            # MEMBERS COUNT
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
            # WHO ADDED BOT
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
            # TEMPORARY INVITE
            # ------------------------------------------------

            invite_url = None

            try:

                expire_time = (
                    datetime.utcnow()
                    + timedelta(
                        minutes=30
                    )
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
            # LOGGER
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

        # ====================================================
        # ADMIN / OWNER
        # ====================================================

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

        # ====================================================
        # APPROVED USER
        # ====================================================

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

        # ====================================================
        # IMMEDIATE JOIN DP SCAN
        # ====================================================

        nsfw_dp = False

        try:

            print(
                f"[DP Scanner] "
                f"Immediately scanning joined "
                f"user DP: {member.id}"
            )

            has_photo, nsfw_dp = (
                await scan_current_profile_photo(
                    client,
                    member.id,
                )
            )

            if not has_photo:

                print(
                    f"[DP Scanner] "
                    f"No DP found for "
                    f"{member.id}"
                )

            elif nsfw_dp:

                print(
                    "================================================"
                )

                print(
                    f"[DP Scanner] 🚨 "
                    f"NSFW DP DETECTED "
                    f"ON JOIN: {member.id}"
                )

                print(
                    f"[DP Scanner] "
                    f"Sending warning immediately..."
                )

                print(
                    "================================================"
                )

                await handle_nsfw_user_violation(
                    client=client,
                    chat_id=chat_id,
                    user_id=member.id,
                    reason="Profile Photo (DP)",
                    message=None,
                )

            else:

                print(
                    f"[DP Scanner] "
                    f"Joined user's DP is clean: "
                    f"{member.id}"
                )

        except Exception as e:

            print(
                f"[DP Scanner] "
                f"Join scan error for "
                f"{member.id}: {e}"
            )

        # ====================================================
        # WELCOME
        # ====================================================

        # NSFW join DP already got warning.
        # Don't send normal welcome in that case.

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
)
async def media_nsfw_checker(
    client: Client,
    message: Message,
):

    if getattr(
        message,
        "service",
        None,
    ):

        return

    if not message.from_user:
        return

    # --------------------------------------------------------
    # Only process media
    # --------------------------------------------------------

    if not (
        message.photo
        or message.sticker
        or message.animation
    ):

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
    # STICKER
    # --------------------------------------------------------

    if message.sticker:

        if (
            message.sticker.is_video
            or message.sticker.is_animated
        ):

            # Try to scan it instead of automatically
            # treating every animated sticker as NSFW.

            file_path = None

            try:

                file_path = await client.download_media(
                    message
                )

                if (
                    file_path
                    and os.path.exists(file_path)
                ):

                    result = await asyncio.to_thread(
                        is_nsfw_media,
                        file_path,
                    )

                    if result is True:

                        await handle_nsfw_violation(
                            client,
                            message,
                            "Video/Animated Sticker",
                        )

            except Exception as e:

                print(
                    f"[Sticker Scanner Error] {e}"
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

            return

    # --------------------------------------------------------
    # MEDIA TYPE
    # --------------------------------------------------------

    if message.photo:

        media_type = "Photo"

    elif message.sticker:

        media_type = "Sticker"

    else:

        media_type = "GIF"

    file_path = None

    try:

        file_path = await client.download_media(
            message
        )

        if (
            not file_path
            or not os.path.exists(file_path)
        ):

            return

        result = await asyncio.to_thread(
            is_nsfw_media,
            file_path,
        )

        if result is True:

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
        # START MESSAGE
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
                f"• Profile Scan On Every Message\n"
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
# /HELP
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

        await query.answer()

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
# /APPROVE
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
# /UNAPPROVE
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
# /BROADCAST
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

    owner_id = get_owner_id()

    if (
        not owner_id
        or message.from_user.id != owner_id
    ):

        return

    if (
        not message.reply_to_message
        and (
            not message.text
            or len(message.command) < 2
        )
    ):

        await message.reply_text(
            "❌ Provide a message or reply to a message."
        )

        return

    args = message.text.split()

    include_users = (
        "-user" in args
    )

    should_pin = (
        "-pin" in args
    )

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
        dict.fromkeys(
            targets
        )
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

            if (
                should_pin
                and sent
            ):

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

    print(
        "=" * 60
    )

    print(
        "VAMPIRE GC PRO Bot Started "
        "Made by Vampire King"
    )

    print(
        "=" * 60
    )

    app.run()
