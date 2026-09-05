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
USER_YTDL_LINKS = {}

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

# 0. /start Command (Works in both DM and Group + Logs new user to LOG_CHANNEL)
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user = message.from_user
    if user and not user.is_bot:
        log_msg = (
            f"👤 <b>New User Started Bot!</b>\n\n"
            f"<b>Name:</b> {user.first_name}\n"
            f"<b>User ID:</b> <code>{user.id}</code>\n"
            f"<b>Username:</b> @{user.username if user.username else 'None'}"
        )
        try:
            await client.send_message(chat_id=LOG_CHANNEL_ID, text=log_msg)
        except Exception:
            pass

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Admin Contact", url="https://t.me/anujith1238")]
    ])
    await message.reply_text(
        "🤖 **I am Leech Bot!**\n"
        "Ready to help you download and manage files.",
        reply_markup=keyboard
    )

# 1. /usetting Command (Group only)
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
    
    elif data.startswith("ytdl_"):
        format_code = data.split("_")[1]
        url = USER_YTDL_LINKS.get(user_id)
        if not url:
            await callback_query.message.edit_text("❌ Link expired or not found. Please send the `/ytdl` command again.")
            return

        await callback_query.message.edit_text("⏳ Initializing download with selected quality... Please wait.")
        await process_download(client, callback_query.message, user_id, callback_query.from_user.first_name, url, format_code)

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

# 2. /v Command
@app.on_message(filters.command("v") & filters.chat(ALLOWED_GROUP_ID))
async def bypass_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a verification link!\nExample: `/v https://shortxlinks.in/xxxx`")
        return

    url = message.command[1]
    msg = await message.reply_text("🔍 Checking link... Please wait.")

    bypassed_link = url
    try:
        api_urls = [
            f"https://api.bypass.vip/bypass?url={url}",
            f"https://bypass.pmh.workers.dev/?url={url}"
        ]
        
        async with aiohttp.ClientSession() as session:
            for api_url in api_urls:
                try:
                    async with session.get(api_url, timeout=10) as resp:
                        if resp.status == 200:
                            res_data = await resp.json()
                            dest = res_data.get("destination") or res_data.get("url")
                            if dest and dest != url:
                                bypassed_link = dest
                                break
                except:
                    continue

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

# 3. /leech Command
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
    await process_download(client, status_msg, user_id, user_name, url, 'best')

# 4. /ytdl & /yt Command
@app.on_message((filters.command("ytdl") | filters.command("yt")) & filters.chat(ALLOWED_GROUP_ID))
async def ytdl_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a YouTube link!\nExample: `/ytdl https://youtu.be/xxxx`")
        return

    url = message.command[1]
    user_id = message.from_user.id
    USER_YTDL_LINKS[user_id] = url

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 144p", callback_data="ytdl_144")],
        [InlineKeyboardButton("📥 240p", callback_data="ytdl_240")],
        [InlineKeyboardButton("📥 360p", callback_data="ytdl_360")],
        [InlineKeyboardButton("📥 480p", callback_data="ytdl_480")],
        [InlineKeyboardButton("📥 720p", callback_data="ytdl_720")],
        [InlineKeyboardButton("📥 1080p", callback_data="ytdl_1080")],
        [InlineKeyboardButton("🎵 MP3 Audio", callback_data="ytdl_mp3")]
    ])

    await message.reply_text(
        "👇 **Select video formatni tanlang:**",
        reply_markup=keyboard
    )

# Common Download & Upload Function (Group First Flow)
async def process_download(client, status_msg, user_id, user_name, url, quality):
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

        if quality == 'mp3':
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'progress_hooks': [download_progress],
            }
        elif quality == 'best':
            ydl_opts = {
                'format': 'best',
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'max_filesize': 2000 * 1024 * 1024,
                'progress_hooks': [download_progress],
            }
        else:
            ydl_opts = {
                'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'max_filesize': 2000 * 1024 * 1024,
                'progress_hooks': [download_progress],
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            if quality == 'mp3':
                file_path = os.path.splitext(file_path)[0] + ".mp3"
            file_title = info_dict.get('title', 'Media')
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        await status_msg.edit_text(
            f"📤 **Uploading to Telegram...**\n\n" \
            f"📁 **Name:** `{file_title}`\n" \
            f"📦 **Size:** `{human_bytes(file_size)}`"
        )

        caption = (
            f"<b>{file_title}</b>\n\n" \
            f"👤 <b>Task By:</b> {user_name} (`{user_id}`)\n" \
            f"📦 <b>Size:</b> {human_bytes(file_size)}\n" \
            f"🔗 <b>Link:</b> {url}"
        )

        thumb = USER_THUMBNAILS.get(user_id)
        valid_thumb = thumb if thumb and os.path.exists(thumb) else None

        # 1. First, send the video/audio directly to the Group
        if quality == 'mp3':
            sent_group_msg = await client.send_audio(
                chat_id=status_msg.chat.id,
                audio=file_path,
                caption=caption,
                thumb=valid_thumb,
                reply_to_message_id=status_msg.reply_to_message_id
            )
        else:
            sent_group_msg = await client.send_video(
                chat_id=status_msg.chat.id,
                video=file_path,
                caption=caption,
                thumb=valid_thumb,
                reply_to_message_id=status_msg.reply_to_message_id
            )

        # 2. Send user info and details to Database Channel
        db_info_text = (
            f"👤 <b>User Name:</b> {user_name}\n" \
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n" \
            f"🔗 <b>Download URL:</b> {url}\n" \
            f"📁 <b>File Name:</b> {file_title}\n" \
            f"📦 <b>File Size:</b> {human_bytes(file_size)}"
        )
        await client.send_message(chat_id=DATABASE_CHANNEL_ID, text=db_info_text)

        # 3. Copy the video to Database Channel as well
        await sent_group_msg.copy(chat_id=DATABASE_CHANNEL_ID)

        # 4. Send log to Log Channel
        log_text = (
            f"📥 <b>New Download Completed!</b>\n\n" \
            f"👤 <b>User:</b> {user_name} (`{user_id}`)\n" \
            f"🔗 <b>URL:</b> {url}\n" \
            f"📁 <b>File:</b> {file_title}\n" \
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
