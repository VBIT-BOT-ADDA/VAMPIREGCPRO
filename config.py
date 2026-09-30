import os


class Config:
    # ============================================================
    # TELEGRAM API
    # ============================================================

    API_ID = int(
        os.environ.get(
            "API_ID",
            "12345678"
        )
    )

    API_HASH = os.environ.get(
        "API_HASH",
        "your_api_hash_here"
    )

    BOT_TOKEN = os.environ.get(
        "BOT_TOKEN",
        "your_bot_token_here"
    )


    # ============================================================
    # MONGODB
    # ============================================================

    MONGO_DB_URI = os.environ.get(
        "MONGO_DB_URI",
        "your_mongodb_uri_here"
    )


    # ============================================================
    # SIGHTENGINE NSFW API
    # ============================================================

    SIGHTENGINE_API_USER = os.environ.get(
        "SIGHTENGINE_API_USER",
        "your_api_user"
    )

    SIGHTENGINE_API_SECRET = os.environ.get(
        "SIGHTENGINE_API_SECRET",
        "your_api_secret"
    )


    # ============================================================
    # WELCOME / START IMAGE
    # ============================================================

    # Main welcome image
    WELCOME_IMAGE = os.environ.get(
        "WELCOME_IMAGE",
        os.environ.get(
            "START_IMG",
            "https://graph.org/file/f681a97d813735f492a83.jpg"
        )
    )

    # Old START_IMG support bhi rakha gaya hai
    START_IMG = os.environ.get(
        "START_IMG",
        WELCOME_IMAGE
    )


    # ============================================================
    # OWNER
    # ============================================================

    # Username @ ke saath ya bina @ ke dono chalega
    OWNER_USERNAME = os.environ.get(
        "OWNER_USERNAME",
        "YourOwnerUsername"
    )

    # Owner Telegram User ID
    OWNER_ID = int(
        os.environ.get(
            "OWNER_ID",
            "8640086543"
        )
    )


    # ============================================================
    # LOGGER
    # ============================================================

    LOGGER_ID = int(
        os.environ.get(
            "LOGGER_ID",
            "-1004434076998"
        )
    )


    # ============================================================
    # SUPPORT / UPDATE
    # ============================================================

    SUPPORT_GROUP = os.environ.get(
        "SUPPORT_GROUP",
        "https://t.me/YourSupportGroup"
    )

    UPDATE_CHANNEL = os.environ.get(
        "UPDATE_CHANNEL",
        "https://t.me/YourUpdateChannel"
    )


    # ============================================================
    # BIO LINK PROTECTION
    # ============================================================

    # Bio me Telegram/channel/group/invite link detect hoga
    BIO_LINK_PROTECTION = os.environ.get(
        "BIO_LINK_PROTECTION",
        "True"
    ).lower() == "true"


    # ============================================================
    # BAD WORD / GAALI PROTECTION
    # ============================================================

    # Message/caption me abusive words detect honge
    BAD_WORD_PROTECTION = os.environ.get(
        "BAD_WORD_PROTECTION",
        "True"
    ).lower() == "true"


    # ============================================================
    # WARNING SYSTEM
    # ============================================================

    # 3 warnings ke baad automatic mute
    MAX_WARNINGS = int(
        os.environ.get(
            "MAX_WARNINGS",
            "3"
        )
    )


    # ============================================================
    # PROTECTION SETTINGS
    # ============================================================

    # Warning message ke neeche buttons
    WARNING_BUTTONS = os.environ.get(
        "WARNING_BUTTONS",
        "True"
    ).lower() == "true"


    # ============================================================
    # BOT BRANDING
    # ============================================================

    BOT_NAME = os.environ.get(
        "BOT_NAME",
        "NSFW PROTECTION BOT"
    )
