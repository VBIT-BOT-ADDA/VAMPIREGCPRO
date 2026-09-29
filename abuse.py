import re
import unicodedata

from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message, ChatPermissions
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

from config import Config


# ============================================================
# MAIN APP
# ============================================================
try:
    from VampirePro import app
except ImportError:
    from bot import app


# ============================================================
# DATABASE
# ============================================================
mongo_client = AsyncIOMotorClient(Config.MONGO_DB_URI)

db = mongo_client["VAMPIREGCPRO_DB"]

approved_db = db["approved_users"]
warnings_db = db["warnings"]


# ============================================================
# BAD WORDS
# ============================================================
BAD_WORDS = [

    # ---------------- ENGLISH ----------------
    "fuck",
    "fucking",
    "fucked",
    "motherfucker",
    "shit",
    "bitch",
    "asshole",
    "bastard",
    "dick",
    "pussy",
    "cunt",
    "whore",
    "slut",
    "sex",
    "sexy",
    "porn",
    "nude",
    "nudes",
    "horny",

    # ---------------- COMMON ----------------
    "video call",
    "available",
    "dm",
    "pm",
    "join",
    "link",
    "desi wife",
    "step bull",

    # ---------------- HINDI / HINGLISH ----------------
    "mc",
    "mkc",
    "madarchod",
    "madrachod",
    "madar chod",
    "bhenchod",
    "behenchod",
    "bhen chod",
    "behen chod",
    "bc",
    "randi",
    "rand",
    "raand",
    "gand",
    "gaand",
    "lund",
    "land",
    "chut",
    "chutiya",
    "chutiye",
    "chuchi",
    "kutta",
    "kutiya",
    "kamina",
    "kamine",
    "harami",
    "haramkhor",
    "besharam",
    "sala",
    "saala",
    "sali",
    "saali",
    "kaand",

    # ---------------- HINDI SCRIPT ----------------
    "मादरचोद",
    "मदरचोद",
    "भेनचोद",
    "बहनचोद",
    "चूतिया",
    "चूत",
    "रंडी",
    "गांड",
    "गंद",
    "लंड",
    "हरामी",
    "हरामखोर",
    "कमीना",
    "कुत्ता",
    "कुतिया",
    "बेशर्म",
    "साला",
    "साली",

    # ---------------- URDU / ROMAN URDU ----------------
    "haramzada",
    "haramzadi",
    "haram zadah",
    "beghairat",
    "bayghairat",
    "kanjar",
    "kanjari",
    "kutti",
    "kuttay",
    "badmaash",
    "harami",

    # Urdu script
    "حرامزادہ",
    "حرامزادی",
    "بےغیرت",
    "کنجر",

    # ---------------- BENGALI / BANGLISH ----------------
    "bokachoda",
    "chodna",
    "chodon",
    "banchod",
    "khankir pola",
    "magir pola",
    "baal",
    "bal",

    # Bengali script
    "বোকাচোদা",
    "চোদনা",
    "চোদন",
    "বাঞ্চোদ",
    "খানকির পোলা",
    "মাগির পোলা",

    # ---------------- ORIGINAL TERMS ----------------
    "service",
    "wife",
    "kiss",
    "gf",
    "bf",
    "ahhh",
    "bio",
]


# ============================================================
# NORMALIZE TEXT
# ============================================================
def normalize_text(text: str) -> str:

    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)

    text = text.casefold()

    # Convert punctuation into spaces.
    text = re.sub(
        r"[^\w]+",
        " ",
        text,
        flags=re.UNICODE,
    )

    text = text.replace("_", " ")

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text


# ============================================================
# PREPARE BAD WORDS
# ============================================================
NORMALIZED_BAD_WORDS = sorted(
    {
        normalize_text(word)
        for word in BAD_WORDS
        if normalize_text(word)
    },
    key=len,
    reverse=True,
)


# ============================================================
# ABUSE REGEX
# ============================================================
ABUSE_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(
        re.escape(word)
        for word in NORMALIZED_BAD_WORDS
    )
    + r")(?!\w)",
    flags=re.IGNORECASE | re.UNICODE,
)


# ============================================================
# TELEGRAM STYLE ENTITIES
# ============================================================
STYLE_ENTITIES = {
    MessageEntityType.BOLD,
    MessageEntityType.ITALIC,
    MessageEntityType.UNDERLINE,
    MessageEntityType.STRIKETHROUGH,
    MessageEntityType.SPOILER,
    MessageEntityType.CUSTOM_EMOJI,
}


# ============================================================
# UNICODE STYLISH FONT DETECTION
# ============================================================
#
# These ranges cover common Mathematical Alphanumeric Symbols:
#
# 𝘼 𝘽 𝘾
# 𝗔 𝗕 𝗖
# 𝑨 𝑩 𝑪
# 𝓐 𝓑 𝓒
# 𝕬 𝕭 𝕮
#
# Normal keyboard A-Z / a-z are NOT matched.
# ============================================================

STYLISH_RANGES = (
    (0x1D400, 0x1D7FF),
    (0x1D200, 0x1D3FF),
)


def contains_unicode_stylish_font(text: str) -> bool:

    if not text:
        return False

    for char in text:

        code = ord(char)

        for start, end in STYLISH_RANGES:

            if start <= code <= end:
                return True

    return False


# ============================================================
# TELEGRAM FORMATTING DETECTION
# ============================================================
def has_forbidden_formatting(message: Message) -> bool:

    entities = []

    if message.entities:
        entities.extend(message.entities)

    if message.caption_entities:
        entities.extend(message.caption_entities)

    for entity in entities:

        if entity.type in STYLE_ENTITIES:
            return True

    return False


# ============================================================
# FINAL STYLE CHECK
# ============================================================
def is_stylish_message(message: Message) -> bool:

    text = (
        message.text
        or message.caption
        or ""
    )

    if not text:
        return False

    # Telegram formatted text
    if has_forbidden_formatting(message):
        return True

    # Unicode stylish fonts
    if contains_unicode_stylish_font(text):
        return True

    return False


# ============================================================
# APPROVED CHECK
# ============================================================
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
            f"[Approved Check Error] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

        return False


# ============================================================
# WARNING COUNTER
# ============================================================
async def increment_warnings(
    chat_id: int,
    user_id: int,
) -> int:

    query = {
        "chat_id": int(chat_id),
        "user_id": int(user_id),
    }

    try:

        result = await warnings_db.find_one_and_update(
            query,
            {
                "$inc": {
                    "count": 1
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        if result:

            return int(
                result.get(
                    "count",
                    1,
                )
            )

    except Exception as e:

        print(
            f"[Warning DB Error] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

    return 1


# ============================================================
# RESET WARNINGS
# ============================================================
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
            f"[Warning Reset Error] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )


# ============================================================
# FIND ABUSIVE WORD
# ============================================================
def find_abusive_word(text: str):

    normalized = normalize_text(text)

    if not normalized:
        return None

    match = ABUSE_PATTERN.search(
        normalized
    )

    if not match:
        return None

    return match.group(0)


# ============================================================
# ABUSE VIOLATION
# ============================================================
async def handle_abuse_violation(
    client: Client,
    message: Message,
    matched_word=None,
):

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # --------------------------------------------------------
    # NO ADMIN / OWNER BYPASS
    # --------------------------------------------------------
    #
    # Admin, owner and normal users are all moderated.
    #
    # Only your existing approved_users whitelist is respected.
    # --------------------------------------------------------

    if await is_user_approved(
        chat_id,
        user_id,
    ):
        return

    user_mention = message.from_user.mention

    # ========================================================
    # DELETE MESSAGE
    # ========================================================
    try:

        await message.delete()

        print(
            f"[Message Deleted] "
            f"chat={chat_id} "
            f"user={user_id} "
            f"reason={matched_word}"
        )

    except Exception as e:

        print(
            f"[Delete Error] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

    # ========================================================
    # WARNING
    # ========================================================
    warn_count = await increment_warnings(
        chat_id,
        user_id,
    )

    # ========================================================
    # WARNING 1/3 OR 2/3
    # ========================================================
    if warn_count < 3:

        try:

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ **Moderation Warning "
                    f"[{warn_count}/3]**\n\n"

                    f"👤 **User:** {user_mention}\n\n"

                    f"🚫 Abusive or prohibited "
                    f"content is not allowed "
                    f"in this group.\n\n"

                    f"🗑 **Your message has been deleted.**\n\n"

                    f"⚠️ Warning: **{warn_count}/3**\n\n"

                    f"🔇 **3 warnings = automatic mute.**"
                ),
            )

        except Exception as e:

            print(
                f"[Warning Message Error] "
                f"chat={chat_id} "
                f"user={user_id}: {e}"
            )

        return

    # ========================================================
    # 3/3 -> MUTE
    # ========================================================
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

                f"👤 **User:** {user_mention}\n\n"

                f"📌 **Reason:** "
                f"3 moderation warnings.\n\n"

                f"🔇 **User has been muted "
                f"automatically.**"
            ),
        )

        await reset_warnings(
            chat_id,
            user_id,
        )

    except Exception as e:

        print(
            f"[Mute Error] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

        try:

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ **Mute failed for "
                    f"{user_mention}.**\n\n"

                    f"Please make sure the bot has "
                    f"permission to restrict members."
                ),
            )

        except Exception as send_error:

            print(
                f"[Mute Error Message Failed] "
                f"{send_error}"
            )


# ============================================================
# STYLISH FONT VIOLATION
# ============================================================
async def handle_style_violation(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Same rule: no admin/owner bypass.
    if await is_user_approved(
        chat_id,
        user_id,
    ):
        return

    user_mention = message.from_user.mention

    # ========================================================
    # DELETE STYLISH MESSAGE
    # ========================================================
    try:

        await message.delete()

        print(
            f"[Stylish Message Deleted] "
            f"chat={chat_id} "
            f"user={user_id}"
        )

    except Exception as e:

        print(
            f"[Stylish Delete Error] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

    # ========================================================
    # ADD WARNING
    # ========================================================
    warn_count = await increment_warnings(
        chat_id,
        user_id,
    )

    # ========================================================
    # WARNING
    # ========================================================
    if warn_count < 3:

        try:

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ **Stylish Font Warning "
                    f"[{warn_count}/3]**\n\n"

                    f"👤 **User:** {user_mention}\n\n"

                    f"🚫 Stylish/bold/decorative "
                    f"font messages are not allowed "
                    f"in this group.\n\n"

                    f"🗑 **Your message has been deleted.**\n\n"

                    f"⚠️ Warning: **{warn_count}/3**\n\n"

                    f"🔇 **3 warnings = automatic mute.**"
                ),
            )

        except Exception as e:

            print(
                f"[Style Warning Error] "
                f"chat={chat_id} "
                f"user={user_id}: {e}"
            )

        return

    # ========================================================
    # 3/3 -> MUTE
    # ========================================================
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

                f"👤 **User:** {user_mention}\n\n"

                f"📌 **Reason:** "
                f"3 warnings for using "
                f"stylish/unsupported font formatting.\n\n"

                f"🔇 **User has been muted "
                f"automatically.**"
            ),
        )

        await reset_warnings(
            chat_id,
            user_id,
        )

    except Exception as e:

        print(
            f"[Style Mute Error] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

        try:

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ **Mute failed for "
                    f"{user_mention}.**\n\n"

                    f"Please make sure the bot has "
                    f"permission to restrict members."
                ),
            )

        except Exception as send_error:

            print(
                f"[Style Mute Message Error] "
                f"{send_error}"
            )


# ============================================================
# HIGH PRIORITY MESSAGE SCANNER
# ============================================================
@app.on_message(
    filters.group
    & ~filters.me
    & ~filters.service
    & (
        filters.text
        | filters.caption
    ),
    group=-1,
)
async def check_group_message(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    text_content = (
        message.text
        or message.caption
        or ""
    )

    if not text_content:
        return

    # ========================================================
    # 1. CHECK STYLISH / FORMATTED FONT
    # ========================================================
    if is_stylish_message(message):

        await handle_style_violation(
            client,
            message,
        )

        return

    # ========================================================
    # 2. CHECK ABUSIVE WORDS
    # ========================================================
    matched_word = find_abusive_word(
        text_content
    )

    if matched_word:

        await handle_abuse_violation(
            client=client,
            message=message,
            matched_word=matched_word,
        )
