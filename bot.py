import os
import time
import logging
import asyncio
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import yt_dlp
from aiohttp import web

# Logging Setup
logging.basicConfig(level=logging.INFO)

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_CHANNEL_ID = int(os.environ.get("DATABASE_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "0"))
ALLOWED_GROUP_ID = int(os.environ.get("ALLOWED_GROUP_ID", "0"))

app = Client("LeechBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

USER_THUMBNAILS = {}
WAITING_FOR_THUMB = set()

# Keep Alive Web Server for Render
async def web_handler(request):
    return web.Response(text="Bot is Live! 🚀")

async def start_web_server():
    web_app = web.Application()
    web_app.add_routes([web.get("/", web_handler)])
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started on port {port}")

# Progress bar function
def human_bytes(size):
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}"

# 0. /start Command with Admin Contact Button
@app.on_message(filters.command("start") & filters.chat(ALLOWED_GROUP_ID))
async def start_handler(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Admin Contact", url="https://t.me/anujith1238")]
    ])
    await message.reply_text(
        "🤖 **I am Leech Bot!**\n"
        "Ready to help you download and manage files.",
        reply_markup=keyboard
    )

# 1. /usetting Command
@app.on_message(filters.command("usetting") & filters.chat(ALLOWED_GROUP_ID))
async def usetting_handler(client: Client, message: Message):
    user_id = message.from_user.id
    has_thumb = "Yes 🖼️" if user_id in USER_THUMBNAILS and USER_THUMBNAILS[user_id] else "No ❌"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Thumbnail Set: {has_thumb}", callback_data="set_thumb")],
        [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="remove_thumb")]
    ])
    
    await message.reply_text(
        "⚙️ **User Personal Settings**\n\n"
        "Configure your personal thumbnail here:",
        reply_markup=keyboard
    )

@app.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if data == "set_thumb":
        WAITING_FOR_THUMB.add(user_id)
        await callback_query.message.edit_text(
            "🖼️ Please send your thumbnail photo (Image) to this group.\n"
            "The bot will automatically save it as your default thumbnail!"
        )
    elif data == "remove_thumb":
        if user_id in USER_THUMBNAILS:
            if os.path.exists(USER_THUMBNAILS[user_id]):
                os.remove(USER_THUMBNAILS[user_id])
            del USER_THUMBNAILS[user_id]
        if user_id in WAITING_FOR_THUMB:
            WAITING_FOR_THUMB.remove(user_id)
            
        await callback_query.message.edit_text("🗑️ Your thumbnail has been successfully removed!")

@app.on_message(filters.photo & filters.chat(ALLOWED_GROUP_ID))
async def save_thumbnail(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in WAITING_FOR_THUMB:
        os.makedirs("thumbnails", exist_ok=True)
        photo_path = f"thumbnails/{user_id}.jpg"
        await message.download(file_name=photo_path)
        USER_THUMBNAILS[user_id] = photo_path
        WAITING_FOR_THUMB.remove(user_id)
        await message.reply_text("✅ Thumbnail saved successfully!")

# 2. /v Command (Open to Everyone - No Admin restriction)
@app.on_message(filters.command("v") & filters.chat(ALLOWED_GROUP_ID))
async def bypass_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a verification link!\nExample: `/v https://vplink.in/xxxx`")
        return

    url = message.command[1]
    msg = await message.reply_text("🔍 Checking link... Please wait.")

    try:
        api_url = f"https://api.bypass.vip/bypass?url={url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    res_data = await resp.json()
                    bypassed_link = res_data.get("destination", url)
                else:
                    bypassed_link = url

        result_text = (
            f"<b>Nick Bypass Bot</b>\n\n"
            f"<b>Original Link :</b> 🔗\n"
            f"✅ <code>{url}</code>\n\n"
            f"<b>Bypassed Link :</b> 🔓\n"
            f"✅ <code>{bypassed_link}</code>"
        )
        await msg.edit_text(result_text)

    except Exception as e:
        await msg.edit_text(f"❌ Failed to bypass link!\n\n**Reason:** `{str(e)}`")

# 3. /leech Command with Progress & Details
@app.on_message(filters.command("leech") & filters.chat(ALLOWED_GROUP_ID))
async def leech_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a link!\nExample: `/leech https://link.com`")
        return

    url = message.command[1]
    user = message.from_user
    user_name = user.first_name if user else "Unknown"
    user_id = user.id if user else 0

    status_msg = await message.reply_text("⏳ Initializing download... Please wait.")

    file_path = None
    try:
        os.makedirs("downloads", exist_ok=True)
        last_update_time = 0

        def download_progress(d):
            nonlocal last_update_time
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update_time > 3:
                    last_update_time = current_time
                    filename = d.get('filename', 'Video')
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    
                    if total > 0:
                        percentage = (downloaded / total) * 100
                        progress_str = f"📥 **Downloading...**\n\n" \
                                       f"📁 **File:** `{os.path.basename(filename)}`\n" \
                                       f"📊 **Progress:** `{percentage:.1f}%`\n" \
                                       f"📦 **Size:** `{human_bytes(downloaded)} / {human_bytes(total)}`"
                    else:
                        progress_str = f"📥 **Downloading...**\n\n" \
                                       f"📁 **File:** `{os.path.basename(filename)}`\n" \
                                       f"📦 **Downloaded:** `{human_bytes(downloaded)}`"
                    
                    try:
                        client.loop.create_task(status_msg.edit_text(progress_str))
                    except Exception:
                        pass

        ydl_opts = {
            'format': 'best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'max_filesize': 2000 * 1024 * 1024,
            'progress_hooks': [download_progress],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            file_title = info_dict.get('title', 'Video')
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        await status_msg.edit_text(
            f"📤 **Uploading to Telegram...**\n\n"
            f"📁 **Name:** `{file_title}`\n"
            f"📦 **Size:** `{human_bytes(file_size)}`"
        )

        caption = (
            f"<b>{file_title}</b>\n\n"
            f"👤 <b>Task By:</b> {user_name} (`{user_id}`)\n"
            f"📦 <b>Size:</b> {human_bytes(file_size)}\n"
            f"🔗 <b>Link:</b> {url}"
        )

        thumb = USER_THUMBNAILS.get(user_id)

        sent_msg = await client.send_video(
            chat_id=DATABASE_CHANNEL_ID,
            video=file_path,
            caption=caption,
            thumb=thumb if thumb and os.path.exists(thumb) else None
        )

        await sent_msg.copy(chat_id=message.chat.id, reply_to_message_id=message.id)

        log_text = (
            f"📥 <b>New Leech Completed!</b>\n\n"
            f"👤 <b>User:</b> {user_name} (`{user_id}`)\n"
            f"🔗 <b>URL:</b> {url}\n"
            f"📁 <b>File:</b> {file_title}\n"
            f"📦 <b>Size:</b> {human_bytes(file_size)}"
        )
        await client.send_message(chat_id=LOG_CHANNEL_ID, text=log_text)

        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ **Download Failed!**\n\n**Reason:** `{str(e)}`")
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def main():
    await start_web_server()
    await app.start()
    print("🤖 Leech Bot Started Successfully...")
    await asyncio.gather(*(asyncio.Event().wait() for _ in range(1)))

if __name__ == "__main__":
    app.loop.run_until_complete(main())
