# VAMPIREGCPRO 🛡️

VAMPIREGCPRO is an advanced AI-powered Telegram group moderation bot designed to scan and eliminate adult (18+/NSFW) profile pictures, stickers, and GIFs, featuring a strict 3-warning auto-mute system.

---

### 🚀 Deploy To Heroku

Click the button below to deploy **VAMPIREGCPRO** directly to Heroku:

<p align="center">
  <a href="https://heroku.com/deploy?template=https://github.com/VBIT-BOT-ADDA/VAMPIREGCPRO">
    <img src="https://img.shields.io/badge/Deploy%20To%20Heroku-SeaGreen?style=for-the-badge&logo=heroku&logoColor=white" alt="Deploy To Heroku">
  </a>
</p>

---

## ✨ Key Features
- 🖼️ **NSFW Profile Picture Scanner**
- 🔞 **18+ Sticker & GIF Auto-Delete**
- ⚠️ **3-Strike Warning & Auto-Mute**
- 🛡️ **`/approve` & `/unapprove` Exemption Commands**
- 📢 **Multi-Mode `/broadcast` Engine**
- 📊 **Logger Channel Integration with 30-min Temporary Group Links**

---

## ⚙️ Environment Variables (Config Vars)

Make sure to set these variables in Heroku during deployment:

| Variable | Description |
| :--- | :--- |
| `API_ID` | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `SIGHTENGINE_API_USER` | API User key from [Sightengine](https://sightengine.com) |
| `SIGHTENGINE_API_SECRET` | API Secret key from [Sightengine](https://sightengine.com) |
| `OWNER_ID` | Owner Telegram Numeric User ID |
| `LOGGER_ID` | Log Channel ID (e.g., `-100123456789`) |
| `OWNER_USERNAME` | Telegram Username without `@` |
| `SUPPORT_GROUP` | Support Group Telegram URL |
| `UPDATE_CHANNEL` | Update Channel Telegram URL |

---

### 📌 Note
After deploying on Heroku, make sure to turn **ON** the `worker` dyno (`worker: python3 bot.py`) under the **Resources** tab!
