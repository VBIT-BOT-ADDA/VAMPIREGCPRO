import os

class Config:
    API_ID = int(os.environ.get("API_ID", "12345678"))
    API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token_here")
    
    # MongoDB Connection URI
    MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "your_mongodb_uri_here")
    
    # Sightengine API Keys (Free account at sightengine.com)
    SIGHTENGINE_API_USER = os.environ.get("SIGHTENGINE_API_USER", "your_api_user")
    SIGHTENGINE_API_SECRET = os.environ.get("SIGHTENGINE_API_SECRET", "your_api_secret")
    
    # Media, Logger & Links
    START_IMG = os.environ.get("START_IMG", "https://graph.org/file/f681a97d813735f492a83.jpg")
    OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "YourOwnerUsername")  # Without @
    OWNER_ID = int(os.environ.get("OWNER_ID", "8640086543"))  # Owner User ID for Broadcast
    LOGGER_ID = int(os.environ.get("LOGGER_ID", "-1004434076998"))  # Log Channel ID
    
    SUPPORT_GROUP = os.environ.get("SUPPORT_GROUP", "https://t.me/YourSupportGroup")
    UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL", "https://t.me/YourUpdateChannel")
    
