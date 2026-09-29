# ============================================================
# VAMPIRE GC PRO - RAW TELEGRAM BIO GUARD
# ============================================================

import re
import time

from pyrogram import filters, raw
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message, ChatPermissions
from pymongo import ReturnDocument


# ============================================================
# BIO LINK DETECTOR
# ============================================================

BIO_URL_REGEX = re.compile(
    r"""
    (?ix)
    (?:
        https?://[^\s]+
        |
        www\.[^\s]+
        |
        (?:t\.me|telegram\.me|telegram\.dog)/[^\s]+
        |
        [a-zA-Z0-9_-]+\.(?:com|org|net|me|in|co|io|xyz|site|online|app|dev|gg|ly|link|store|shop|live|pro|info|biz|tech|cloud|fun|top|vip|club|click|icu|cc|tv)
        (?:/[^\s]*)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ============================================================
# RAW TELEGRAM BIO FETCH
# ============================================================

async def get_raw_user_bio(client, user_id: int) -> str:
    """
    Fetch actual Telegram profile Bio using
    users.GetFullUser.
    """

    try:
        peer = await client.resolve_peer(int(user_id))

        # Convert InputPeerUser -> InputUser
        if not hasattr(peer, "user_id"):
            print(
                f"[BIO RAW] Could not resolve user: {user_id}"
            )
            return ""

        input_user = raw.types.InputUser(
            user_id=peer.user_id,
            access_hash=peer.access_hash,
        )

        result = await client.invoke(
            raw.functions.users.GetFullUser(
                id=input_user
            )
        )

        if not result:
            return ""

        full_user = getattr(
            result,
            "full_user",
            None,
        )

        if not full_user:
            return ""

        bio = getattr(
            full_user,
            "about",
            None,
        )

        if not bio:
            return ""

        # Remove invisible Unicode characters
        bio = re.sub(
            r"[\u200b-\u200f\u202a-\u202e\ufeff]",
            "",
            bio,
        )

        return bio.strip()

    except Exception as e:
        print(
            f"[BIO RAW FETCH ERROR] "
            f"user={user_id} | "
            f"{type(e).__name__}: {e}"
        )
        return ""


# ============================================================
# DETECT LINK
# ============================================================

def find_bio_link(bio: str):

    if not bio:
        return None

    match = BIO_URL_REGEX.search(bio)

    if match:
        return match.group(0)

    return None


# ============================================================
# ADMIN / OWNER PROTECTION
# ============================================================

async def bio_admin_check(
    client,
    chat_id: int,
    user_id: int,
):

    # Bot owner
    try:
        if int(user_id) == int(Config.OWNER_ID):
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

async def bio_approved_check(
    chat_id: int,
    user_id: int,
):

    try:

        return bool(
            await approved_db.find_one(
                {
                    "chat_id": int(chat_id),
                    "user_id": int(user_id),
                }
            )
        )

    except Exception as e:

        print(
            f"[BIO APPROVED CHECK ERROR] "
            f"{chat_id}/{user_id}: {e}"
        )

        return False


# ============================================================
# WARNING COUNTER
# ============================================================

async def bio_warning(
    chat_id: int,
    user_id: int,
):

    try:

        result = await warnings_db.find_one_and_update(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            },

            {
                "$inc": {
                    "bio_warnings": 1,
                },

                "$set": {
                    "bio_warning_updated": time.time(),
                },
            },

            upsert=True,

            return_document=ReturnDocument.AFTER,
        )

        if result:
            return int(
                result.get(
                    "bio_warnings",
                    1,
                )
            )

    except Exception as e:

        print(
            f"[BIO WARNING ERROR] {e}"
        )

    return 1


# ============================================================
# RESET BIO WARNINGS
# ============================================================

async def bio_reset(
    chat_id: int,
    user_id: int,
):

    try:

        await warnings_db.update_one(
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
            },

            {
                "$unset": {
                    "bio_warnings": "",
                    "bio_warning_updated": "",
                }
            },
        )

    except Exception as e:

        print(
            f"[BIO RESET ERROR] {e}"
        )


# ============================================================
# FORCE DELETE
# ============================================================

async def bio_delete_message(
    client,
    message: Message,
):

    try:

        await client.delete_messages(
            chat_id=message.chat.id,
            message_ids=[message.id],
        )

        print(
            f"✅ BIO MESSAGE DELETED | "
            f"chat={message.chat.id} | "
            f"message={message.id}"
        )

        return True

    except Exception as e:

        print(
            f"❌ BIO DELETE FAILED | "
            f"chat={message.chat.id} | "
            f"message={message.id} | "
            f"{type(e).__name__}: {e}"
        )

        return False


# ============================================================
# MUTE
# ============================================================

async def bio_mute_user(
    client,
    chat_id: int,
    user_id: int,
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
            f"🔇 BIO USER MUTED | "
            f"{chat_id}/{user_id}"
        )

        return True

    except Exception as e:

        print(
            f"❌ BIO MUTE FAILED | "
            f"{chat_id}/{user_id} | "
            f"{type(e).__name__}: {e}"
        )

        return False


# ============================================================
# BIO VIOLATION
# ============================================================

async def bio_violation(
    client,
    message: Message,
    detected_link: str,
):

    if not message.from_user:
        return

    chat_id = int(message.chat.id)
    user_id = int(message.from_user.id)

    # --------------------------------------------------------
    # ADMIN / OWNER
    # --------------------------------------------------------

    if await bio_admin_check(
        client,
        chat_id,
        user_id,
    ):
        return

    # --------------------------------------------------------
    # APPROVED
    # --------------------------------------------------------

    if await bio_approved_check(
        chat_id,
        user_id,
    ):
        return

    # --------------------------------------------------------
    # DELETE FIRST
    # --------------------------------------------------------

    await bio_delete_message(
        client,
        message,
    )

    # --------------------------------------------------------
    # WARNING
    # --------------------------------------------------------

    count = await bio_warning(
        chat_id,
        user_id,
    )

    mention = message.from_user.mention

    # --------------------------------------------------------
    # 1/3
    # --------------------------------------------------------

    if count == 1:

        await client.send_message(
            chat_id,

            f"🚨 **BIO LINK WARNING [1/3]**\n\n"
            f"👤 {mention}\n\n"
            f"🔗 A link was detected in your "
            f"Telegram profile Bio.\n\n"
            f"🗑 Your message was deleted.\n"
            f"⚠️ Remove the link from your Bio."
        )

        return

    # --------------------------------------------------------
    # 2/3
    # --------------------------------------------------------

    if count == 2:

        await client.send_message(
            chat_id,

            f"⚠️ **BIO LINK WARNING [2/3]**\n\n"
            f"👤 {mention}\n\n"
            f"🔗 Your Bio still contains a link.\n\n"
            f"🗑 Your message was deleted.\n"
            f"⚠️ Remove the link immediately."
        )

        return

    # --------------------------------------------------------
    # 3/3
    # --------------------------------------------------------

    if count == 3:

        await client.send_message(
            chat_id,

            f"🚨 **FINAL BIO WARNING [3/3]**\n\n"
            f"👤 {mention}\n\n"
            f"🔗 Your Bio still contains a link.\n\n"
            f"🗑 Your message was deleted.\n\n"
            f"🔇 **NEXT MESSAGE = MUTE**"
        )

        return

    # --------------------------------------------------------
    # 4TH VIOLATION
    # --------------------------------------------------------

    if count >= 4:

        muted = await bio_mute_user(
            client,
            chat_id,
            user_id,
        )

        if muted:

            await client.send_message(
                chat_id,

                f"🔇 **USER MUTED**\n\n"
                f"👤 {mention}\n\n"
                f"📌 Bio link remained after "
                f"3 warnings.\n\n"
                f"🚫 User has been muted automatically."
            )

            await bio_reset(
                chat_id,
                user_id,
            )


# ============================================================
# MAIN BIO SCANNER
# ============================================================

@app.on_message(
    filters.group
    & ~filters.service
    & ~filters.me,
    group=-1000,
)
async def raw_bio_guard(
    client,
    message: Message,
):

    try:

        # ====================================================
        # BASIC
        # ====================================================

        if not message.from_user:
            return

        if message.from_user.is_bot:
            return

        chat_id = int(message.chat.id)
        user_id = int(message.from_user.id)

        # ====================================================
        # ADMIN
        # ====================================================

        if await bio_admin_check(
            client,
            chat_id,
            user_id,
        ):
            return

        # ====================================================
        # APPROVED
        # ====================================================

        if await bio_approved_check(
            chat_id,
            user_id,
        ):
            return

        # ====================================================
        # RAW TELEGRAM BIO
        # ====================================================

        bio = await get_raw_user_bio(
            client,
            user_id,
        )

        print(
            f"🔎 BIO SCAN | "
            f"user={user_id} | "
            f"bio={bio!r}"
        )

        if not bio:
            return

        # ====================================================
        # LINK DETECTION
        # ====================================================

        link = find_bio_link(
            bio
        )

        if not link:
            return

        # ====================================================
        # DETECTED
        # ====================================================

        print(
            "\n"
            "==========================================\n"
            "🚨 BIO LINK DETECTED\n"
            f"USER : {user_id}\n"
            f"CHAT : {chat_id}\n"
            f"LINK : {link}\n"
            f"BIO  : {bio}\n"
            "=========================================="
        )

        # ====================================================
        # DELETE + WARN / MUTE
        # ====================================================

        await bio_violation(
            client,
            message,
            link,
        )

    except Exception as e:

        print(
            f"🔥 BIO GUARD ERROR | "
            f"{type(e).__name__}: {e}"
        )
