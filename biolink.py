import re
import time
import asyncio

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message, ChatPermissions
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

from config import Config


# ============================================================
# APP
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
# SETTINGS
# ============================================================

MAX_WARNINGS = 3

# Warning 1 -> delete + warning
# Warning 2 -> delete + warning
# Warning 3 -> delete + final warning
# Warning 4 -> delete + mute

MUTE_AFTER = 3


# ============================================================
# LINK / DOMAIN DETECTOR
# ============================================================

BIO_LINK_REGEX = re.compile(
    r"""
    (?ix)

    # HTTP / HTTPS
    https?://[^\s]+

    |

    # WWW
    www\.[^\s]+

    |

    # Telegram links
    (?:https?://)?(?:www\.)?
    (?:t\.me|telegram\.me|telegram\.dog)/
    [^\s]+

    |

    # Telegram username
    (?:^|\s)@
    [a-zA-Z0-9_]{4,32}

    |

    # Normal domains
    \b
    (?:[a-zA-Z0-9-]+\.)+
    (?:
        com
        |net
        |org
        |me
        |in
        |co
        |io
        |xyz
        |site
        |online
        |app
        |dev
        |gg
        |ly
        |link
        |store
        |shop
        |live
        |pro
        |info
        |biz
        |tech
        |cloud
        |fun
        |top
        |vip
        |club
        |click
        |icu
        |cc
        |tv
    )
    (?:/[^\s]*)?
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ============================================================
# BIO TEXT NORMALIZER
# ============================================================

def normalize_bio(text: str) -> str:

    if not text:
        return ""

    # Remove zero-width characters
    text = re.sub(
        r"[\u200b-\u200f\u202a-\u202e\ufeff]",
        "",
        text,
    )

    # Normalize spaces
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# BIO LINK CHECK
# ============================================================

def detect_bio_link(bio: str):

    bio = normalize_bio(bio)

    if not bio:
        return False, None

    match = BIO_LINK_REGEX.search(bio)

    if match:
        return True, match.group(0)

    return False, None


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

        return result is not None

    except Exception as e:

        print(
            f"[APPROVED CHECK ERROR] "
            f"{chat_id}/{user_id}: {e}"
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
    # BOT OWNER
    # --------------------------------------------------------

    try:

        owner_id = int(
            str(
                getattr(
                    Config,
                    "OWNER_ID",
                    0,
                )
            ).strip()
        )

        if owner_id and int(user_id) == owner_id:
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
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        ):
            return True

    except Exception as e:

        print(
            f"[ADMIN CHECK ERROR] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

    return False


# ============================================================
# GET CURRENT USER BIO
# ============================================================

async def get_current_user_bio(
    client: Client,
    user_id: int,
):
    """
    Fresh Telegram profile lookup.
    No cache.
    """

    try:

        user = await client.get_users(
            int(user_id)
        )

        if not user:
            return ""

        bio = getattr(
            user,
            "bio",
            None,
        )

        return normalize_bio(
            bio or ""
        )

    except Exception as e:

        print(
            f"[BIO FETCH ERROR] "
            f"user={user_id}: {e}"
        )

        # Second fallback
        try:

            chat = await client.get_chat(
                int(user_id)
            )

            bio = getattr(
                chat,
                "bio",
                None,
            )

            return normalize_bio(
                bio or ""
            )

        except Exception as fallback_error:

            print(
                f"[BIO FALLBACK ERROR] "
                f"user={user_id}: "
                f"{fallback_error}"
            )

            return ""


# ============================================================
# ATOMIC WARNING COUNTER
# ============================================================

async def add_warning(
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

            return int(
                result.get(
                    "count",
                    1,
                )
            )

    except Exception as e:

        print(
            f"[WARNING DB ERROR] "
            f"{chat_id}/{user_id}: {e}"
        )

    return 1


# ============================================================
# GET WARNING COUNT
# ============================================================

async def get_warning_count(
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

    except Exception:

        return 0


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
            f"[WARNING RESET ERROR] "
            f"{chat_id}/{user_id}: {e}"
        )


# ============================================================
# SAFE DELETE
# ============================================================

async def safe_delete(
    message: Message,
) -> bool:

    try:

        await message.delete()

        print(
            f"[BIO MESSAGE DELETED] "
            f"chat={message.chat.id} "
            f"user={message.from_user.id if message.from_user else 'UNKNOWN'}"
        )

        return True

    except Exception as e:

        print(
            f"[MESSAGE DELETE ERROR] "
            f"message={message.id}: {e}"
        )

        return False


# ============================================================
# SAFE MUTE
# ============================================================

async def mute_user(
    client: Client,
    chat_id: int,
    user_id: int,
) -> bool:

    try:

        await client.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
        )

        print(
            f"[BIO USER MUTED] "
            f"chat={chat_id} "
            f"user={user_id}"
        )

        return True

    except Exception as e:

        print(
            f"[MUTE ERROR] "
            f"chat={chat_id} "
            f"user={user_id}: {e}"
        )

        return False


# ============================================================
# BIO VIOLATION
# ============================================================

async def process_bio_violation(
    client: Client,
    message: Message,
    detected_link: str = None,
):

    if not message.from_user:
        return

    chat_id = int(
        message.chat.id
    )

    user_id = int(
        message.from_user.id
    )

    # ========================================================
    # HARD PROTECTION
    # ========================================================

    if await is_admin_or_owner(
        client,
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # APPROVED USER
    # ========================================================

    if await is_user_approved(
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # DELETE IMMEDIATELY
    # ========================================================

    await safe_delete(
        message
    )

    # ========================================================
    # ADD WARNING
    # ========================================================

    warning = await add_warning(
        chat_id,
        user_id,
    )

    mention = message.from_user.mention

    # ========================================================
    # WARNING 1
    # ========================================================

    if warning == 1:

        try:

            await client.send_message(
                chat_id,

                f"🚨 **BIO LINK WARNING [1/3]**\n\n"
                f"👤 {mention}\n\n"
                f"Your Telegram profile Bio contains "
                f"a link or website.\n\n"
                f"🗑 Your message has been removed.\n"
                f"⚠️ Please remove the link from your Bio.\n\n"
                f"🔒 **3 warnings = final warning.**"
            )

        except Exception as e:

            print(
                f"[WARNING 1 SEND ERROR] {e}"
            )

        return

    # ========================================================
    # WARNING 2
    # ========================================================

    if warning == 2:

        try:

            await client.send_message(
                chat_id,

                f"⚠️ **BIO LINK WARNING [2/3]**\n\n"
                f"👤 {mention}\n\n"
                f"The link is still present in your "
                f"Telegram profile Bio.\n\n"
                f"🗑 Your message was removed.\n"
                f"❗ Remove the link from your Bio.\n\n"
                f"🚨 **One final warning remains.**"
            )

        except Exception as e:

            print(
                f"[WARNING 2 SEND ERROR] {e}"
            )

        return

    # ========================================================
    # WARNING 3
    # ========================================================

    if warning == 3:

        try:

            await client.send_message(
                chat_id,

                f"🚨 **FINAL BIO WARNING [3/3]**\n\n"
                f"👤 {mention}\n\n"
                f"The link is still present in your "
                f"Telegram profile Bio.\n\n"
                f"🗑 Your message was removed.\n\n"
                f"⚠️ **NEXT VIOLATION = MUTE**"
            )

        except Exception as e:

            print(
                f"[WARNING 3 SEND ERROR] {e}"
            )

        return

    # ========================================================
    # 4TH VIOLATION -> MUTE
    # ========================================================

    if warning >= 4:

        muted = await mute_user(
            client,
            chat_id,
            user_id,
        )

        if muted:

            try:

                await client.send_message(
                    chat_id,

                    f"🔇 **USER MUTED**\n\n"
                    f"👤 {mention}\n\n"
                    f"📌 Reason: Bio link remained "
                    f"after **3 warnings**.\n\n"
                    f"🚫 The user has been muted "
                    f"automatically."
                )

            except Exception as e:

                print(
                    f"[MUTE MESSAGE ERROR] {e}"
                )

            # Start fresh
            await reset_warnings(
                chat_id,
                user_id,
            )

        else:

            try:

                await client.send_message(
                    chat_id,

                    f"❌ **Could not mute {mention}.**\n\n"
                    f"Please make sure I have "
                    f"permission to restrict members."
                )

            except Exception as e:

                print(
                    f"[MUTE FAIL MESSAGE ERROR] {e}"
                )


# ============================================================
# MAIN BIO GUARD
# ============================================================

@app.on_message(
    filters.group
    & ~filters.service
    & ~filters.me,
    group=-100,
)
async def professional_bio_guard(
    client: Client,
    message: Message,
):

    # ========================================================
    # BASIC VALIDATION
    # ========================================================

    if not message.from_user:
        return

    if message.from_user.is_bot:
        return

    chat_id = int(
        message.chat.id
    )

    user_id = int(
        message.from_user.id
    )

    # ========================================================
    # ADMIN / OWNER BYPASS
    # ========================================================

    if await is_admin_or_owner(
        client,
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # APPROVED BYPASS
    # ========================================================

    if await is_user_approved(
        chat_id,
        user_id,
    ):
        return

    # ========================================================
    # GET FRESH BIO
    # ========================================================

    bio = await get_current_user_bio(
        client,
        user_id,
    )

    if not bio:
        return

    # ========================================================
    # DETECT
    # ========================================================

    detected, link = detect_bio_link(
        bio
    )

    if not detected:
        return

    # ========================================================
    # LOG
    # ========================================================

    print(
        "\n"
        "============================================\n"
        "🚨 BIO LINK DETECTED\n"
        f"CHAT      : {chat_id}\n"
        f"USER      : {user_id}\n"
        f"LINK      : {link}\n"
        f"BIO       : {bio}\n"
        "============================================"
    )

    # ========================================================
    # DELETE + WARN / MUTE
    # ========================================================

    await process_bio_violation(
        client=client,
        message=message,
        detected_link=link,
    )


# ============================================================
# APPROVE
# ============================================================

@app.on_message(
    filters.group
    & filters.command("approve"),
)
async def approve_user_command(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    chat_id = int(
        message.chat.id
    )

    admin_id = int(
        message.from_user.id
    )

    if not await is_admin_or_owner(
        client,
        chat_id,
        admin_id,
    ):

        await message.reply_text(
            "❌ **Admin / Owner only.**"
        )

        return

    # --------------------------------------------------------
    # REPLY TARGET
    # --------------------------------------------------------

    target_message = (
        message.reply_to_message
    )

    if not target_message:

        await message.reply_text(
            "⚠️ **Reply to the user's message and use /approve.**"
        )

        return

    if not target_message.from_user:

        await message.reply_text(
            "❌ **Could not identify the user.**"
        )

        return

    target_id = int(
        target_message.from_user.id
    )

    # --------------------------------------------------------
    # SAVE APPROVAL
    # --------------------------------------------------------

    try:

        await approved_db.update_one(
            {
                "chat_id": chat_id,
                "user_id": target_id,
            },

            {
                "$set": {
                    "chat_id": chat_id,
                    "user_id": target_id,
                    "approved_at": time.time(),
                }
            },

            upsert=True,
        )

        # Reset old warnings
        await reset_warnings(
            chat_id,
            target_id,
        )

        await message.reply_text(
            "✅ **User Approved Successfully**\n\n"
            f"👤 {target_message.from_user.mention}\n\n"
            "Bio link checking is now bypassed "
            "for this user in this group."
        )

    except Exception as e:

        print(
            f"[APPROVE ERROR] "
            f"{chat_id}/{target_id}: {e}"
        )

        await message.reply_text(
            "❌ Failed to approve user."
        )


# ============================================================
# UNAPPROVE
# ============================================================

@app.on_message(
    filters.group
    & filters.command("unapprove"),
)
async def unapprove_user_command(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    chat_id = int(
        message.chat.id
    )

    admin_id = int(
        message.from_user.id
    )

    if not await is_admin_or_owner(
        client,
        chat_id,
        admin_id,
    ):

        await message.reply_text(
            "❌ **Admin / Owner only.**"
        )

        return

    target_message = (
        message.reply_to_message
    )

    if not target_message:

        await message.reply_text(
            "⚠️ **Reply to the user's message and use /unapprove.**"
        )

        return

    if not target_message.from_user:

        await message.reply_text(
            "❌ **Could not identify the user.**"
        )

        return

    target_id = int(
        target_message.from_user.id
    )

    # --------------------------------------------------------
    # REMOVE APPROVAL
    # --------------------------------------------------------

    try:

        await approved_db.delete_one(
            {
                "chat_id": chat_id,
                "user_id": target_id,
            }
        )

        await message.reply_text(
            "🚫 **User Unapproved**\n\n"
            f"👤 {target_message.from_user.mention}\n\n"
            "Bio link scanning is active again."
        )

    except Exception as e:

        print(
            f"[UNAPPROVE ERROR] "
            f"{chat_id}/{target_id}: {e}"
        )

        await message.reply_text(
            "❌ Failed to unapprove user."
        )


# ============================================================
# STARTUP
# ============================================================

print(
    "=============================================="
)

print(
    "🛡️ VAMPIRE GC PRO - PROFESSIONAL BIO GUARD"
)

print(
    "✅ Fresh Bio Detection"
)

print(
    "✅ Instant Message Delete"
)

print(
    "✅ 3 Warning System"
)

print(
    "✅ 4th Violation Auto Mute"
)

print(
    "✅ Admin / Owner Protection"
)

print(
    "✅ Approve / Unapprove System"
)

print(
    "=============================================="
)
