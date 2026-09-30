import os
import re
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
    InlineKeyboardButton as PyrogramInlineKeyboardButton,
    CallbackQuery,
)

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

from config import Config


# ============================================================
# BUTTON STYLE COMPATIBILITY FIX
# ============================================================

try:
    from pyrogram.enums import ButtonStyle
    BUTTON_STYLE_SUPPORTED = True

except ImportError:

    BUTTON_STYLE_SUPPORTED = False

    class ButtonStyle:
        DEFAULT = "DEFAULT"
        PRIMARY = "PRIMARY"
        DANGER = "DANGER"
        SUCCESS = "SUCCESS"


# ============================================================
# OLD PYROGRAM COMPATIBILITY
# ============================================================

if BUTTON_STYLE_SUPPORTED:

    InlineKeyboardButton = PyrogramInlineKeyboardButton

else:

    def InlineKeyboardButton(
        *args,
        style=None,
        **kwargs
    ):

        return PyrogramInlineKeyboardButton(
            *args,
            **kwargs
        )


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
            "NSFW_PROTECTION_BOT",
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
            {"user_id": int(user_id)},
            {"$set": {"user_id": int(user_id)}},
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
            {"chat_id": int(chat_id)},
            {"$set": {"chat_id": int(chat_id)}},
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
    user_id: int
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
    user_id: int
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
    user_id: int
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
    user_id: int
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
            doc.get("count", 0)
        )

    except Exception as e:

        print(
            f"[Warning Read Error] {e}"
        )

        return 0


async def increment_warnings(
    chat_id: int,
    user_id: int
) -> int:

    try:

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
            result.get("count", 1)
        )

    except Exception as e:

        print(
            f"[Warning Increment Error] {e}"
        )

        return 1


async def reset_warnings(
    chat_id: int,
    user_id: int
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
# OWNER / ADMIN CHECK
# ============================================================

def get_owner_id():

    try:

        return int(
            str(
                getattr(
                    Config,
                    "OWNER_ID",
                    0
                )
            ).strip()
        )

    except Exception:

        return 0


def get_owner_username():

    try:

        username = getattr(
            Config,
            "OWNER_USERNAME",
            None
        )

        if username:

            username = str(
                username
            ).strip()

            username = username.replace(
                "https://t.me/",
                ""
            )

            username = username.replace(
                "http://t.me/",
                ""
            )

            username = username.replace(
                "@",
                ""
            )

            username = username.strip("/")

            if username:
                return username

    except Exception:
        pass

    return ""


def get_owner_url():

    username = get_owner_username()

    if username:

        return f"https://t.me/{username}"

    owner_id = get_owner_id()

    if owner_id:

        return f"tg://user?id={owner_id}"

    return "https://t.me/"


async def is_admin_or_owner(
    client: Client,
    chat_id: int,
    user_id: int
) -> bool:

    if not user_id:
        return True

    try:

        owner_id = get_owner_id()

        if owner_id and int(user_id) == owner_id:
            return True

    except Exception:
        pass

    try:

        member = await client.get_chat_member(
            chat_id,
            user_id
        )

        if member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            return True

    except Exception as e:

        print(
            f"[Admin Check Error] {e}"
        )

    return False


# ============================================================
# WELCOME IMAGE HELPERS
# ============================================================

def get_welcome_image():

    try:

        image = getattr(
            Config,
            "WELCOME_IMAGE",
            None
        )

        if image:

            image = str(
                image
            ).strip()

            if image:
                return image

    except Exception as e:

        print(
            f"[Welcome Image Config Error] {e}"
        )

    return None


async def prepare_welcome_image():

    image = get_welcome_image()

    if not image:
        return None

    # --------------------------------------------------------
    # LOCAL FILE
    # --------------------------------------------------------

    if os.path.exists(image):

        return image

    # --------------------------------------------------------
    # TELEGRAM FILE ID / OTHER NON-URL VALUE
    # --------------------------------------------------------

    if not (
        image.startswith("http://")
        or image.startswith("https://")
    ):

        return image

    # --------------------------------------------------------
    # DIRECT IMAGE URL
    # --------------------------------------------------------

    try:

        response = await asyncio.to_thread(
            requests.get,
            image,
            timeout=20,
            stream=True,
        )

        if response.status_code != 200:

            print(
                f"[Welcome Image HTTP Error] "
                f"{response.status_code}"
            )

            return image

        content_type = (
            response.headers.get(
                "content-type",
                ""
            ).lower()
        )

        extension = ".jpg"

        if "png" in content_type:
            extension = ".png"

        elif "webp" in content_type:
            extension = ".webp"

        elif "jpeg" in content_type:
            extension = ".jpg"

        image_path = os.path.join(
            "/tmp",
            "nsfw_protection_welcome" + extension
        )

        def save_image():

            with open(
                image_path,
                "wb"
            ) as file:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if chunk:
                        file.write(chunk)

        await asyncio.to_thread(
            save_image
        )

        if os.path.exists(image_path):

            if os.path.getsize(image_path) > 0:
                return image_path

    except Exception as e:

        print(
            f"[Welcome Image Download Error] {e}"
        )

    return image


# ============================================================
# BIO LINK + PROFANITY DETECTOR
# ============================================================

BIO_SCAN_CACHE = {}
BIO_SCAN_CACHE_TTL = 15

# Telegram group/channel/invite links.
TELEGRAM_LINK_PATTERN = re.compile(
    r"(?i)(?:https?://)?(?:www\.)?"
    r"(?:t\.me|telegram\.me|telegram\.dog)/"
    r"(?:\+|joinchat/|[A-Za-z0-9_+\-]+)"
)

# Common abusive/profanity words. Word boundaries are used to reduce
# false positives such as matching a short word inside a normal word.
PROFANITY_WORDS = (
    "bc", "mc", "bkl", "bsdk", "bhosdi", "bhosdike",
    "bhosdika", "bhosdiwala", "bhosdiwale",
    "madarchod", "madarchuda", "madarchodne",
    "behenchod", "behenchoda", "behnchod", "behenchode",
    "chutiya", "chutiye", "chuti", "chod", "chodna", "chodu",
    "fuck", "fucker", "fucking", "motherfucker",
    "bitch", "bitches", "asshole", "bastard",
    "harami", "haramkhor", "kamina", "kamine", "kaminey",
    "kutte", "kutta", "randi", "gandu", "gaand", "gand",
    "लौड़ा", "लौड़े", "लौडी", "चूतिया", "चूतिये", "चूत",
    "भोसड़ी", "भोसड़ीके", "भोसडी", "भोसडीके",
    "मादरचोद", "मदरचोद", "बहनचोद", "भेनचोद",
    "हरामी", "हरामखोर", "कमीना", "कमीने", "कुत्ता", "कुत्ते",
)

PROFANITY_PATTERN = re.compile(
    r"(?i)(?<![\w])(?:"
    + "|".join(re.escape(word) for word in sorted(PROFANITY_WORDS, key=len, reverse=True))
    + r")(?![\w])"
)


def contains_telegram_link(text: str) -> bool:
    if not text:
        return False

    try:
        return bool(TELEGRAM_LINK_PATTERN.search(str(text)))
    except Exception:
        return False


def contains_profanity(text: str) -> bool:
    if not text:
        return False

    try:
        value = str(text).replace("\u200b", " ").replace("\u200c", " ")
        return bool(PROFANITY_PATTERN.search(value))
    except Exception:
        return False


def get_user_bio_text(user) -> str:
    try:
        return str(getattr(user, "bio", None) or "").strip()
    except Exception:
        return ""


async def get_user_bio(client: Client, user_id: int) -> str:
    now = time.time()
    cached = BIO_SCAN_CACHE.get(user_id)

    if cached and now - cached.get("time", 0) < BIO_SCAN_CACHE_TTL:
        return cached.get("bio", "")

    try:
        user = await client.get_users(user_id)
        bio = get_user_bio_text(user)

        BIO_SCAN_CACHE[user_id] = {
            "bio": bio,
            "time": now,
        }

        if len(BIO_SCAN_CACHE) > 5000:
            oldest = sorted(
                BIO_SCAN_CACHE.items(),
                key=lambda item: item[1].get("time", 0),
            )[:500]

            for key, _ in oldest:
                BIO_SCAN_CACHE.pop(key, None)

        return bio

    except Exception as e:
        print(f"[Bio Scan Error] {e}")
        return ""


def get_warning_markup():
    buttons = []
    support_group = getattr(Config, "SUPPORT_GROUP", None)
    update_channel = getattr(Config, "UPDATE_CHANNEL", None)

    row = []

    if update_channel:
        row.append(
            InlineKeyboardButton(
                text="🚀 Update",
                url=str(update_channel).strip(),
                style=ButtonStyle.PRIMARY,
            )
        )

    if support_group:
        row.append(
            InlineKeyboardButton(
                text="💬 Support",
                url=str(support_group).strip(),
                style=ButtonStyle.PRIMARY,
            )
        )

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons) if buttons else None


def get_warning_text(reason: str, warn_count: int, user_mention: str) -> str:
    reason_lower = str(reason).lower()

    if "bio" in reason_lower:
        description = (
            "your **bio** contains a Telegram group/channel link "
            "which is not allowed and was removed."
        )
        title = "🚨 **Bio Link Warning"
    elif "profanity" in reason_lower or "abusive" in reason_lower:
        description = (
            "your message contains abusive/profane language "
            "which is not allowed and was removed."
        )
        title = "🚨 **Abusive Language Warning"
    else:
        description = (
            f"your **{reason}** contains adult content "
            "and was removed."
        )
        title = "🚨 **NSFW Warning"

    return (
        f"{title} [{warn_count}/3]**\n\n"
        f"Hey {user_mention}, {description}\n\n"
        f"⚠️ **3 warnings will result in an automatic mute.**"
    )


# ============================================================
# END BIO LINK + PROFANITY DETECTOR
# ============================================================


# ============================================================
# SIGHTENGINE NSFW DETECTOR
# ============================================================

def is_nsfw_media(file_path: str):

    api_user = getattr(
        Config,
        "SIGHTENGINE_API_USER",
        None
    )

    api_secret = getattr(
        Config,
        "SIGHTENGINE_API_SECRET",
        None
    )

    if (
        not api_user
        or not api_secret
        or not file_path
        or not os.path.exists(file_path)
    ):
        return None

    url = (
        "https://api.sightengine.com/1.0/check.json"
    )

    params = {
        "models": "nudity-2.0,wad",
        "api_user": api_user,
        "api_secret": api_secret,
    }

    try:

        with open(
            file_path,
            "rb"
        ) as image_file:

            response = requests.post(
                url,
                files={
                    "media": (
                        os.path.basename(file_path),
                        image_file
                    )
                },
                data=params,
                timeout=15,
            )

        try:

            data = response.json()

        except Exception:

            print(
                f"[NSFW Engine Error] Invalid API response: "
                f"{response.text[:500]}"
            )

            return None

        if data.get("status") != "success":

            print(
                f"[Sightengine Error] "
                f"{data.get('error', data)}"
            )

            return None

        nudity = data.get(
            "nudity",
            {}
        )

        sexual_activity = float(
            nudity.get(
                "sexual_activity",
                0
            ) or 0
        )

        sexual_display = float(
            nudity.get(
                "sexual_display",
                0
            ) or 0
        )

        erotica = float(
            nudity.get(
                "erotica",
                0
            ) or 0
        )

        suggestive = float(
            nudity.get(
                "suggestive",
                0
            ) or 0
        )

        score = max(
            sexual_activity,
            sexual_display,
            erotica,
            suggestive,
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
    user_id: int
):

    try:

        user = await client.get_users(
            user_id
        )

        return user.mention

    except Exception:

        return f"`{user_id}`"


# ============================================================
# NSFW VIOLATION HANDLER
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

    if await is_admin_or_owner(
        client,
        chat_id,
        user_id
    ):
        return False

    if await is_user_approved(
        chat_id,
        user_id
    ):
        return False

    if message is not None:

        try:

            await message.delete()

            print(
                f"[NSFW Deleted] "
                f"{reason} | "
                f"User: {user_id}"
            )

        except Exception as e:

            print(
                f"[Delete Error] {e}"
            )

    warn_count = await increment_warnings(
        chat_id,
        user_id
    )

    user_mention = await get_user_mention(
        client,
        user_id
    )

    if warn_count < 3:

        try:

            await client.send_message(
                chat_id=chat_id,
                text=get_warning_text(
                    reason,
                    warn_count,
                    user_mention,
                ),
                reply_markup=get_warning_markup(),
            )

        except Exception as e:

            print(
                f"[Warning Message Error] {e}"
            )

        return True

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
                f"🚫 **User Muted!**\n\n"
                f"**User:** {user_mention}\n"
                f"**Reason:** 3/3 warnings reached for **{reason}**."
            ),
            reply_markup=get_warning_markup(),
        )

        await reset_warnings(
            chat_id,
            user_id
        )

        return True

    except Exception as e:

        print(
            f"[Mute Error] {e}"
        )

        return False


# ============================================================
# PROFILE PHOTO SCANNER
# ============================================================

async def scan_current_profile_photo(
    client: Client,
    user_id: int
):

    lock = get_profile_lock(
        user_id
    )

    async with lock:

        try:

            user = await client.get_users(
                user_id
            )

            if not user or not user.photo:
                return False, False

            file_id = (
                getattr(
                    user.photo,
                    "big_file_id",
                    None
                )
                or
                getattr(
                    user.photo,
                    "small_file_id",
                    None
                )
            )

            if not file_id:
                return False, False

            cache = PROFILE_SCAN_CACHE.get(
                user_id
            )

            if (
                cache
                and cache.get("file_id") == file_id
            ):

                return (
                    True,
                    bool(
                        cache.get(
                            "is_nsfw",
                            False
                        )
                    )
                )

            dp_path = await client.download_media(
                file_id
            )

            if (
                not dp_path
                or not os.path.exists(dp_path)
            ):
                return True, False

            scan_result = await asyncio.to_thread(
                is_nsfw_media,
                dp_path
            )

            nsfw = (
                bool(scan_result)
                if scan_result is not None
                else False
            )

            PROFILE_SCAN_CACHE[user_id] = {
                "file_id": file_id,
                "is_nsfw": nsfw,
                "time": time.time(),
            }

            cleanup_profile_cache()

            if os.path.exists(dp_path):

                try:
                    os.remove(dp_path)
                except Exception:
                    pass

            return True, nsfw

        except Exception as e:

            print(
                f"[DP Scan Error] {e}"
            )

            return True, False


# ============================================================
# PROFILE SCAN ON EVERY MESSAGE
# ============================================================

@app.on_message(
    filters.group,
    group=-10
)
async def profile_scan_handler(
    client: Client,
    message: Message
):

    if (
        getattr(
            message,
            "service",
            None
        )
        or not message.from_user
        or message.from_user.is_bot
    ):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    if await is_admin_or_owner(
        client,
        chat_id,
        user_id
    ):
        return

    if await is_user_approved(
        chat_id,
        user_id
    ):
        return

    # ------------------------------------------------------------
    # BIO LINK DETECTOR
    # ------------------------------------------------------------

    try:
        user_bio = await get_user_bio(
            client,
            user_id
        )

        if contains_telegram_link(user_bio):

            print(
                f"[BIO LINK DETECTED] "
                f"User: {user_id}"
            )

            await handle_nsfw_user_violation(
                client=client,
                chat_id=chat_id,
                user_id=user_id,
                reason="Bio Link",
                message=message,
            )

            # One message = one warning. Do not continue to the
            # other scanners after this violation.
            return

    except Exception as e:

        print(
            f"[Bio Link Handler Error] {e}"
        )

    # ------------------------------------------------------------
    # PROFANITY / ABUSIVE LANGUAGE DETECTOR
    # ------------------------------------------------------------

    message_text = (
        getattr(message, "text", None)
        or getattr(message, "caption", None)
        or ""
    )

    if contains_profanity(message_text):

        print(
            f"[PROFANITY DETECTED] "
            f"User: {user_id}"
        )

        await handle_nsfw_user_violation(
            client=client,
            chat_id=chat_id,
            user_id=user_id,
            reason="Abusive Language",
            message=message,
        )

        # One message = one warning.
        return

    # ------------------------------------------------------------
    # EXISTING PROFILE PHOTO / NSFW SCANNER
    # ------------------------------------------------------------

    has_photo, nsfw = await scan_current_profile_photo(
        client,
        user_id
    )

    if has_photo and nsfw:

        await handle_nsfw_user_violation(
            client=client,
            chat_id=chat_id,
            user_id=user_id,
            reason="Profile Photo (DP)",
            message=message,
        )


# ============================================================
# FIXED STICKER / GIF / PHOTO SCANNER
# ============================================================

@app.on_message(
    filters.group
    & (
        filters.sticker
        | filters.animation
        | filters.photo
    ),
    group=-5
)
async def media_nsfw_checker(
    client: Client,
    message: Message
):

    if getattr(
        message,
        "service",
        None
    ):
        return

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    if await is_admin_or_owner(
        client,
        chat_id,
        user_id
    ):
        return

    if await is_user_approved(
        chat_id,
        user_id
    ):
        return

    if message.sticker:

        if getattr(
            message.sticker,
            "is_video",
            False
        ):

            print(
                f"[Video Sticker] "
                f"Detected from user {user_id}"
            )

            await handle_nsfw_user_violation(
                client=client,
                chat_id=chat_id,
                user_id=user_id,
                reason="Video Sticker",
                message=message,
            )

            return

        if getattr(
            message.sticker,
            "is_animated",
            False
        ):

            print(
                f"[Animated Sticker] "
                f"Detected from user {user_id}"
            )

            await handle_nsfw_user_violation(
                client=client,
                chat_id=chat_id,
                user_id=user_id,
                reason="Animated Sticker",
                message=message,
            )

            return

    file_path = None

    if message.photo:

        media_type = "Photo"

    elif message.sticker:

        media_type = "Sticker"

    elif message.animation:

        media_type = "GIF"

    else:

        media_type = "Media"

    try:

        file_path = await client.download_media(
            message
        )

        if (
            not file_path
            or not os.path.exists(file_path)
        ):

            print(
                f"[Media Download Error] "
                f"{media_type}"
            )

            return

        print(
            f"[NSFW Scan] "
            f"{media_type} -> {file_path}"
        )

        scan_result = await asyncio.to_thread(
            is_nsfw_media,
            file_path
        )

        if scan_result is True:

            await handle_nsfw_user_violation(
                client=client,
                chat_id=chat_id,
                user_id=user_id,
                reason=media_type,
                message=message,
            )

        elif scan_result is None:

            print(
                f"[NSFW Scan Failed] "
                f"{media_type}"
            )

    except Exception as e:

        print(
            f"[Media Checker Error] {e}"
        )

    finally:

        if (
            file_path
            and os.path.exists(file_path)
        ):

            try:
                os.remove(file_path)
            except Exception:
                pass


# ============================================================
# START COMMAND
# WELCOME MESSAGE + BUTTONS
# ============================================================

@app.on_message(
    filters.command("start")
    & filters.private
)
async def start_cmd(
    client: Client,
    message: Message
):

    if message.from_user:

        await add_served_user(
            message.from_user.id
        )

    try:

        me = await client.get_me()
        bot_username = me.username

    except Exception:

        bot_username = ""

    support_group = getattr(
        Config,
        "SUPPORT_GROUP",
        None
    )

    update_channel = getattr(
        Config,
        "UPDATE_CHANNEL",
        None
    )

    buttons = []

    if bot_username:

        buttons.append(
            [
                InlineKeyboardButton(
                    text="➕ Add Me To Your Group ➕",
                    url=(
                        f"https://t.me/"
                        f"{bot_username}"
                        f"?startgroup=true"
                    ),
                    style=ButtonStyle.PRIMARY
                )
            ]
        )

    row_2 = []

    if support_group:

        row_2.append(
            InlineKeyboardButton(
                text="💬 Support Group",
                url=support_group,
                style=ButtonStyle.PRIMARY
            )
        )

    if update_channel:

        row_2.append(
            InlineKeyboardButton(
                text="📢 Update Channel",
                url=update_channel,
                style=ButtonStyle.PRIMARY
            )
        )

    if row_2:

        buttons.append(row_2)

    buttons.append(
        [
            InlineKeyboardButton(
                text="👑 Owner",
                url=get_owner_url(),
                style=ButtonStyle.PRIMARY
            ),

            InlineKeyboardButton(
                text="❓ Help & Commands",
                callback_data="help_commands",
                style=ButtonStyle.DANGER
            )
        ]
    )

    reply_markup = InlineKeyboardMarkup(
        buttons
    )

    user_mention = (
        message.from_user.mention
        if message.from_user
        else "User"
    )

    welcome_text = (
        f"👋 Hello {user_mention}!\n\n"
        f"🤖 **Welcome to NSFW PROTECTION BOT!**\n\n"
        f"An advanced AI-powered Telegram group moderation bot.\n\n"
        f"✨ **Core Features:**\n"
        f"• NSFW Profile Picture Scanning\n"
        f"• Adult 18+ Sticker & GIF Auto-Delete\n"
        f"• 3-Strike Warning & Auto-Mute System\n"
        f"• Group Protection & Automatic Moderation\n"
        f"• 24/7 Online Protection\n\n"
        f"🛡️ Keep your group safe, clean & protected!"
    )

    # ========================================================
    # WELCOME IMAGE
    # ========================================================

    try:

        welcome_image = await prepare_welcome_image()

        if welcome_image:

            try:

                await client.send_photo(
                    chat_id=message.chat.id,
                    photo=welcome_image,
                    caption=welcome_text,
                    reply_markup=reply_markup
                )

                return

            except Exception as image_error:

                print(
                    f"[Welcome Image Send Error] "
                    f"{image_error}"
                )

        await message.reply_text(
            welcome_text,
            reply_markup=reply_markup
        )

    except Exception as e:

        print(
            f"[Welcome Message Error] {e}"
        )

        try:

            await message.reply_text(
                welcome_text,
                reply_markup=reply_markup
            )

        except Exception as error:

            print(
                f"[Welcome Fallback Error] {error}"
            )


# ============================================================
# HELP & COMMANDS
# ============================================================

@app.on_callback_query(
    filters.regex("^help_commands$")
)
async def help_commands_callback(
    client: Client,
    callback_query: CallbackQuery
):

    help_text = (
        "🛡️ **NSFW PROTECTION BOT**\n\n"
        "✨ **Available Commands:**\n\n"
        "• `/start` — Start the bot\n"
        "• `/approve` — Approve a user\n"
        "• `/unapprove` — Remove user approval\n\n"
        "🔰 **Protection:**\n"
        "• NSFW profile picture scanning\n"
        "• NSFW photo detection\n"
        "• Adult sticker detection\n"
        "• GIF detection\n"
        "• Automatic message deletion\n"
        "• 3-warning auto mute system\n\n"
        "👑 Admins and approved users are bypassed."
    )

    back_button = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="🔙 Back",
                    callback_data="back_start",
                    style=ButtonStyle.PRIMARY
                )
            ]
        ]
    )

    try:

        await callback_query.message.edit_caption(
            caption=help_text,
            reply_markup=back_button
        )

    except Exception:

        try:

            await callback_query.message.edit_text(
                text=help_text,
                reply_markup=back_button
            )

        except Exception as e:

            print(
                f"[Help Callback Error] {e}"
            )

    try:
        await callback_query.answer()
    except Exception:
        pass


# ============================================================
# BACK BUTTON
# ============================================================

@app.on_callback_query(
    filters.regex("^back_start$")
)
async def back_start_callback(
    client: Client,
    callback_query: CallbackQuery
):

    try:

        me = await client.get_me()
        bot_username = me.username

    except Exception:

        bot_username = ""

    support_group = getattr(
        Config,
        "SUPPORT_GROUP",
        None
    )

    update_channel = getattr(
        Config,
        "UPDATE_CHANNEL",
        None
    )

    buttons = []

    if bot_username:

        buttons.append(
            [
                InlineKeyboardButton(
                    text="➕ Add Me To Your Group ➕",
                    url=(
                        f"https://t.me/"
                        f"{bot_username}"
                        f"?startgroup=true"
                    ),
                    style=ButtonStyle.PRIMARY
                )
            ]
        )

    row_2 = []

    if support_group:

        row_2.append(
            InlineKeyboardButton(
                text="💬 Support Group",
                url=support_group,
                style=ButtonStyle.PRIMARY
            )
        )

    if update_channel:

        row_2.append(
            InlineKeyboardButton(
                text="📢 Update Channel",
                url=update_channel,
                style=ButtonStyle.PRIMARY
            )
        )

    if row_2:

        buttons.append(row_2)

    buttons.append(
        [
            InlineKeyboardButton(
                text="👑 Owner",
                url=get_owner_url(),
                style=ButtonStyle.PRIMARY
            ),

            InlineKeyboardButton(
                text="❓ Help & Commands",
                callback_data="help_commands",
                style=ButtonStyle.DANGER
            )
        ]
    )

    reply_markup = InlineKeyboardMarkup(
        buttons
    )

    user = callback_query.from_user

    user_mention = (
        user.mention
        if user
        else "User"
    )

    welcome_text = (
        f"👋 Hello {user_mention}!\n\n"
        f"🤖 **Welcome to NSFW PROTECTION BOT!**\n\n"
        f"An advanced AI-powered Telegram group moderation bot.\n\n"
        f"✨ **Core Features:**\n"
        f"• NSFW Profile Picture Scanning\n"
        f"• Adult 18+ Sticker & GIF Auto-Delete\n"
        f"• 3-Strike Warning & Auto-Mute System\n"
        f"• Group Protection & Automatic Moderation\n"
        f"• 24/7 Online Protection\n\n"
        f"🛡️ Keep your group safe, clean & protected!"
    )

    try:

        welcome_image = await prepare_welcome_image()

        if welcome_image:

            try:

                await callback_query.message.delete()

                await client.send_photo(
                    chat_id=callback_query.message.chat.id,
                    photo=welcome_image,
                    caption=welcome_text,
                    reply_markup=reply_markup
                )

            except Exception as e:

                print(
                    f"[Back Photo Error] {e}"
                )

                try:

                    await client.send_message(
                        chat_id=callback_query.message.chat.id,
                        text=welcome_text,
                        reply_markup=reply_markup
                    )

                except Exception as fallback_error:

                    print(
                        f"[Back Photo Fallback Error] "
                        f"{fallback_error}"
                    )

        else:

            await callback_query.message.edit_text(
                welcome_text,
                reply_markup=reply_markup
            )

    except Exception as e:

        print(
            f"[Back Callback Error] {e}"
        )

    try:

        await callback_query.answer()

    except Exception:
        pass


# ============================================================
# APPROVE COMMAND
# ============================================================

@app.on_message(
    filters.group
    & filters.command("approve")
)
async def approve_cmd(
    client: Client,
    message: Message
):

    if not message.from_user:
        return

    if not await is_admin_or_owner(
        client,
        message.chat.id,
        message.from_user.id
    ):

        return await message.reply_text(
            "❌ Admin command only."
        )

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):

        target = (
            message.reply_to_message
            .from_user
            .id
        )

        await approve_user_db(
            message.chat.id,
            target
        )

        await message.reply_text(
            "✅ User approved."
        )


# ============================================================
# UNAPPROVE COMMAND
# ============================================================

@app.on_message(
    filters.group
    & filters.command("unapprove")
)
async def unapprove_cmd(
    client: Client,
    message: Message
):

    if not message.from_user:
        return

    if not await is_admin_or_owner(
        client,
        message.chat.id,
        message.from_user.id
    ):

        return await message.reply_text(
            "❌ Admin command only."
        )

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):

        target = (
            message.reply_to_message
            .from_user
            .id
        )

        await unapprove_user_db(
            message.chat.id,
            target
        )

        await message.reply_text(
            "🚫 User unapproved."
        )


# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":

    print(
        "============================================================"
    )

    print(
        "NSFW PROTECTION BOT Started"
    )

    print(
        "============================================================"
    )

    app.run()
