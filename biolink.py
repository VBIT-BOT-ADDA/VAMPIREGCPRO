# ============================================================
# VAMPIRE GC PRO - BIO LINK GUARD PRO
# ============================================================

import re
import time
import asyncio

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message, ChatPermissions
from pymongo import ReturnDocument


# ============================================================
# DATABASE
# ============================================================

# IMPORTANT:
# Existing db / approved_db / warnings_db ko reuse karo.
# Agar tumhare main file me ye already defined hain,
# to inhe dobara define mat karna.


# ============================================================
# BIO LINK REGEX
# ============================================================

BIO_LINK_REGEX = re.compile(
    r"""
    (?ix)

    # http / https
    https?://[^\s]+

    |

    # www
    www\.[^\s]+

    |

    # telegram
    (?:https?://)?(?:www\.)?
    (?:t\.me|telegram\.me|telegram\.dog)/
    [^\s]+

    |

    # @username
    (?:^|\s)@[a-zA-Z0-9_]{4,32}

    |

    # domains
    \b
    (?:[a-zA-Z0-9-]+\.)+
    (?:
        com|org|net|me|in|co|io|xyz|site|online|
        app|dev|gg|ly|link|store|shop|live|pro|
        info|biz|tech|cloud|fun|top|vip|club|click|
        icu|cc|tv
    )
    (?:/[^\s]*)?

    """,
    re.IGNORECASE | re.VERBOSE,
)


# ============================================================
# WARNING SETTINGS
# ============================================================

BIO_MUTE_AFTER = 3


# ============================================================
# NORMALIZE BIO
# ============================================================

def normalize_bio(text):

    if not text:
        return ""

    # Zero-width characters remove
    text = re.sub(
        r"[\u200b-\u200f\u202a-\u202e\ufeff]",
        "",
        text,
    )

    # New lines / multiple spaces normalize
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# DETECT LINK
# ============================================================

def detect_bio_link(bio):

    bio = normalize_bio(bio)

    if not bio:
        return None

    match = BIO_LINK_REGEX.search(bio)

    if match:
        return match.group(0)

    return None


# ============================================================
# ADMIN / OWNER
# ============================================================

async def bio_is_admin_or_owner(
    client,
    chat_id,
    user_id,
):

    if not user_id:
        return True

    # Bot owner
    try:

        owner_id = int(
            str(
                getattr(
                    Config,
                    "OWNER_ID",
                    0,
                )
            )
        )

        if owner_id == int(user_id):
            return True

    except Exception:
        pass

    # Group admin / owner
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
            f"[BIO ADMIN CHECK ERROR] "
            f"{chat_id}/{user_id}: {e}"
        )

    return False


# ============================================================
# APPROVED CHECK
# ============================================================

async def bio_is_approved(
    chat_id,
    user_id,
):

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
            f"[BIO APPROVED ERROR] "
            f"{chat_id}/{user_id}: {e}"
        )

        return False


# ============================================================
# GET FRESH BIO
# ============================================================

async def fetch_fresh_bio(
    client,
    user_id,
):

    # --------------------------------------------------------
    # METHOD 1 - get_chat
    # --------------------------------------------------------

    try:

        user_chat = await client.get_chat(
            int(user_id)
        )

        bio = getattr(
            user_chat,
            "bio",
            None,
        )

        if bio:
            return normalize_bio(bio)

    except Exception as e:

        print(
            f"[BIO get_chat ERROR] "
            f"user={user_id}: {e}"
        )

    # --------------------------------------------------------
    # METHOD 2 - get_users
    # --------------------------------------------------------

    try:

        user = await client.get_users(
            int(user_id)
        )

        bio = getattr(
            user,
            "bio",
            None,
        )

        if bio:
            return normalize_bio(bio)

    except Exception as e:

        print(
            f"[BIO get_users ERROR] "
            f"user={user_id}: {e}"
        )

    return ""


# ============================================================
# ATOMIC WARNING
# ============================================================

async def bio_add_warning(
    chat_id,
    user_id,
):

    query = {
        "chat_id": int(chat_id),
        "user_id": int(user_id),
    }

    try:

        result = await warnings_db.find_one_and_update(
            query,

            {
                "$inc": {
                    "bio_count": 1,
                },

                "$set": {
                    "bio_updated_at": time.time(),
                },
            },

            upsert=True,

            return_document=ReturnDocument.AFTER,
        )

        if result:

            return int(
                result.get(
                    "bio_count",
                    1,
                )
            )

    except Exception as e:

        print(
            f"[BIO WARNING DB ERROR] "
            f"{chat_id}/{user_id}: {e}"
        )

    return 1


# ============================================================
# RESET BIO WARNINGS
# ============================================================

async def bio_reset_warnings(
    chat_id,
    user_id,
):

    try:

        await warnings_db.update_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            },

            {
                "$unset": {
                    "bio_count": "",
                    "bio_updated_at": "",
                }
            },
        )

    except Exception as e:

        print(
            f"[BIO RESET ERROR] "
            f"{chat_id}/{user_id}: {e}"
        )


# ============================================================
# FORCE DELETE
# ============================================================

async def bio_force_delete(
    client,
    message,
):

    try:

        # Direct delete by chat + message ID
        await client.delete_messages(
            chat_id=message.chat.id,
            message_ids=message.id,
        )

        print(
            f"✅ [BIO MESSAGE DELETED] "
            f"chat={message.chat.id} "
            f"message={message.id}"
        )

        return True

    except Exception as e:

        print(
            f"❌ [BIO DELETE FAILED] "
            f"chat={message.chat.id} "
            f"message={message.id} "
            f"ERROR={e}"
        )

        return False


# ============================================================
# FORCE MUTE
# ============================================================

async def bio_force_mute(
    client,
    chat_id,
    user_id,
):

    try:

        await client.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,

            permissions=ChatPermissions(
                can_send_messages=False,
            ),
        )

        print(
            f"🔇 [BIO USER MUTED] "
            f"{chat_id}/{user_id}"
        )

        return True

    except Exception as e:

        print(
            f"❌ [BIO MUTE FAILED] "
            f"{chat_id}/{user_id}: {e}"
        )

        return False


# ============================================================
# HANDLE BIO VIOLATION
# ============================================================

async def bio_handle_violation(
    client,
    message,
    detected_link,
):

    if not message.from_user:
        return

    chat_id = int(
        message.chat.id
    )

    user_id = int(
        message.from_user.id
    )

    # --------------------------------------------------------
    # ADMIN / OWNER
    # --------------------------------------------------------

    if await bio_is_admin_or_owner(
        client,
        chat_id,
        user_id,
    ):
        return

    # --------------------------------------------------------
    # APPROVED
    # --------------------------------------------------------

    if await bio_is_approved(
        chat_id,
        user_id,
    ):
        return

    # --------------------------------------------------------
    # DELETE FIRST
    # --------------------------------------------------------

    deleted = await bio_force_delete(
        client,
        message,
    )

    if not deleted:
        print(
            "⚠️ Bio violation detected "
            "but Telegram refused message deletion."
        )

    # --------------------------------------------------------
    # WARNING
    # --------------------------------------------------------

    warning = await bio_add_warning(
        chat_id,
        user_id,
    )

    mention = message.from_user.mention

    # --------------------------------------------------------
    # 1/3
    # --------------------------------------------------------

    if warning == 1:

        try:

            await client.send_message(
                chat_id,

                f"🚨 **BIO LINK WARNING [1/3]**\n\n"
                f"👤 {mention}\n\n"
                f"🔗 A link/website was detected "
                f"in your Telegram Bio.\n\n"
                f"🗑 Your message was removed.\n\n"
                f"⚠️ Remove the link from your Bio."
            )

        except Exception as e:

            print(
                f"[BIO WARNING 1 ERROR] {e}"
            )

        return

    # --------------------------------------------------------
    # 2/3
    # --------------------------------------------------------

    if warning == 2:

        try:

            await client.send_message(
                chat_id,

                f"⚠️ **BIO LINK WARNING [2/3]**\n\n"
                f"👤 {mention}\n\n"
                f"🔗 The link is still present "
                f"in your Bio.\n\n"
                f"🗑 Your message was removed.\n\n"
                f"⚠️ Remove the link immediately."
            )

        except Exception as e:

            print(
                f"[BIO WARNING 2 ERROR] {e}"
            )

        return

    # --------------------------------------------------------
    # 3/3
    # --------------------------------------------------------

    if warning == 3:

        try:

            await client.send_message(
                chat_id,

                f"🚨 **FINAL BIO WARNING [3/3]**\n\n"
                f"👤 {mention}\n\n"
                f"🔗 Your Bio still contains a link.\n\n"
                f"🗑 Your message was removed.\n\n"
                f"🔇 **NEXT VIOLATION = MUTE**"
            )

        except Exception as e:

            print(
                f"[BIO WARNING 3 ERROR] {e}"
            )

        return

    # --------------------------------------------------------
    # 4TH MESSAGE -> MUTE
    # --------------------------------------------------------

    if warning >= 4:

        muted = await bio_force_mute(
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
                    f"📌 Bio link remained after "
                    f"3 warnings.\n\n"
                    f"🚫 User has been muted automatically."
                )

            except Exception as e:

                print(
                    f"[BIO MUTE MESSAGE ERROR] {e}"
                )

            await bio_reset_warnings(
                chat_id,
                user_id,
            )


# ============================================================
# MAIN BIO GUARD
# ============================================================

@app.on_message(
    filters.group
    & ~filters.service
    & ~filters.me,
    group=-999,
)
async def bio_guard_pro(
    client,
    message: Message,
):

    try:

        # ====================================================
        # USER CHECK
        # ====================================================

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

        # ====================================================
        # ADMIN
        # ====================================================

        if await bio_is_admin_or_owner(
            client,
            chat_id,
            user_id,
        ):
            return

        # ====================================================
        # APPROVED
        # ====================================================

        if await bio_is_approved(
            chat_id,
            user_id,
        ):
            return

        # ====================================================
        # GET CURRENT BIO
        # ====================================================

        bio = await fetch_fresh_bio(
            client,
            user_id,
        )

        # ====================================================
        # DEBUG
        # ====================================================

        print(
            f"[BIO CHECK] "
            f"user={user_id} "
            f"bio={bio!r}"
        )

        if not bio:
            return

        # ====================================================
        # DETECT
        # ====================================================

        detected_link = detect_bio_link(
            bio
        )

        if not detected_link:
            return

        # ====================================================
        # DETECTED
        # ====================================================

        print(
            "\n"
            "============================================\n"
            "🚨🚨 BIO LINK DETECTED 🚨🚨\n"
            f"CHAT: {chat_id}\n"
            f"USER: {user_id}\n"
            f"LINK: {detected_link}\n"
            f"BIO : {bio}\n"
            "============================================"
        )

        # ====================================================
        # DELETE + WARNING / MUTE
        # ====================================================

        await bio_handle_violation(
            client,
            message,
            detected_link,
        )

    except Exception as e:

        print(
            f"🔥 [BIO GUARD CRITICAL ERROR] "
            f"{type(e).__name__}: {e}"
        )


# ============================================================
# BIO GUARD READY
# ============================================================

print(
    "🛡️ BIO GUARD PRO LOADED | "
    "Fresh Scan + Force Delete + 3 Warning + Auto Mute"
)
