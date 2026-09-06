import os
import time
import logging
import asyncio
import aiohttp
import subprocess
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import yt_dlp
from aiohttp import web

# Logging Setup
logging.basicConfig(level=logging.INFO)

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_CHANNEL_ID = int(os.environ.get("DATABASE_CHANNEL_ID", "-1004396122384"))
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "-1004441596603"))
ALLOWED_GROUP_ID = int(os.environ.get("ALLOWED_GROUP_ID", "0"))

ADMIN_ID = 1727225499

app = Client("LeechBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

USER_THUMBNAILS = {}
USER_FILE_MODES = {}  # user_id: "video" or "document"
WAITING_FOR_THUMB = set()
USER_YTDL_LINKS = {}

ACTIVE_TASKS = {}
USER_TASK_LIMIT = 2
CANCEL_REQUESTS = set()

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

def human_bytes(size):
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}"

def get_video_info(file_path):
    duration = 0
    width = 0
    height = 0
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration:stream=width,height",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 3:
            width = int(lines[0]) if lines[0].isdigit() else 0
            height = int(lines[1]) if lines[1].isdigit() else 0
            duration = int(float(lines[2])) if lines[2] else 0
    except Exception as e:
        logging.error(f"Error getting video info: {e}")
    return duration, width, height

def generate_thumbnail(video_path, user_id):
    os.makedirs("thumbnails", exist_ok=True)
    thumb_path = f"thumbnails/auto_{user_id}.jpg"
    try:
        cmd = [
            "ffmpeg", "-ss", "00:00:05", "-i", video_path,
            "-vframes", "1", "-q:v", "2", thumb_path, "-y"
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception as e:
        logging.error(f"Error generating thumbnail: {e}")
    return None

async def download_image_from_url(url, save_path):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(save_path, "wb") as f:
                        f.write(data)
                    return True
    except Exception as e:
        logging.error(f"Failed to download thumbnail from URL: {e}")
    return False

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
        except Exception as e:
            logging.error(f"Failed to send start log to LOG_CHANNEL: {e}")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Admin Contact", url="https://t.me/anujith1238")]
    ])
    await message.reply_text(
        "🤖 **I am Leech Bot!**\n"
        "Ready to help you download and manage files.",
        reply_markup=keyboard
    )

@app.on_message(filters.command("usetting") & filters.chat(ALLOWED_GROUP_ID))
async def usetting_handler(client: Client, message: Message):
    user_id = message.from_user.id
    has_thumb = "Yes 🖼️" if user_id in USER_THUMBNAILS and USER_THUMBNAILS[user_id] else "No ❌"
    current_mode = USER_FILE_MODES.get(user_id, "video")
    mode_text = "📹 Video Format" if current_mode == "video" else "📁 Document Format"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Thumbnail Set: {has_thumb}", callback_data="set_thumb")],
        [InlineKeyboardButton(f"Mode: {mode_text}", callback_data="toggle_mode")],
        [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="remove_thumb")]
    ])
    
    await message.reply_text(
        "⚙️ **User Personal Settings**\n\n"
        "Configure your personal thumbnail and upload format here:",
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
    elif data == "toggle_mode":
        current_mode = USER_FILE_MODES.get(user_id, "video")
        new_mode = "document" if current_mode == "video" else "video"
        USER_FILE_MODES[user_id] = new_mode
        
        has_thumb = "Yes 🖼️" if user_id in USER_THUMBNAILS and USER_THUMBNAILS[user_id] else "No ❌"
        mode_text = "📹 Video Format" if new_mode == "video" else "📁 Document Format"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Thumbnail Set: {has_thumb}", callback_data="set_thumb")],
            [InlineKeyboardButton(f"Mode: {mode_text}", callback_data="toggle_mode")],
            [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="remove_thumb")]
        ])
        await callback_query.message.edit_reply_markup(reply_markup=keyboard)
        await callback_query.answer(f"Format updated to {new_mode}!")

    elif data == "remove_thumb":
        if user_id in USER_THUMBNAILS:
            if os.path.exists(USER_THUMBNAILS[user_id]):
                os.remove(USER_THUMBNAILS[user_id])
            del USER_THUMBNAILS[user_id]
        if user_id in WAITING_FOR_THUMB:
            WAITING_FOR_THUMB.remove(user_id)
            
        await callback_query.message.edit_text("🗑️ Your thumbnail has been successfully removed!")
    
    elif data.startswith("cancel_dl_"):
        task_user_id = int(data.split("_")[2])
        if user_id == task_user_id or user_id == ADMIN_ID:
            CANCEL_REQUESTS.add(task_user_id)
            await callback_query.answer("⚠️ Task cancellation requested. Stopping task...", show_alert=True)
        else:
            await callback_query.answer("❌ You are not authorized to cancel this task!", show_alert=True)

    elif data.startswith("ytdl_"):
        format_code = data.split("_")[1]
        url = USER_YTDL_LINKS.get(user_id)
        if not url:
            await callback_query.message.edit_text("❌ Link expired or not found. Please send the `/ytdl` command again.")
            return

        if user_id != ADMIN_ID:
            active_count = ACTIVE_TASKS.get(user_id, 0)
            if active_count >= USER_TASK_LIMIT:
                await callback_query.message.edit_text(
                    f"⚠️ **Limit Exceeded!**\n\n"
                    f"You already have `{active_count}` active downloads running. "
                    f"Please wait for them to finish before starting a new one (Max allowed: {USER_TASK_LIMIT})."
                )
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

@app.on_message(filters.command("leech") & filters.chat(ALLOWED_GROUP_ID))
async def leech_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a link!\nExample: `/leech https://link.com -n NewName -thumb https://image.url`")
        return

    raw_text = message.text.split(" ", 1)[1]
    
    url = raw_text
    custom_name = None
    custom_thumb_url = None
    
    if "-thumb" in raw_text:
        parts = raw_text.split("-thumb")
        url = parts[0].strip()
        custom_thumb_url = parts[1].strip().split(" ")[0]
        if "-n" in parts[0]:
            sub_parts = parts[0].split("-n")
            url = sub_parts[0].strip()
            custom_name = sub_parts[1].strip()
    elif "-n" in raw_text:
        parts = raw_text.split("-n")
        url = parts[0].strip()
        custom_name = parts[1].strip().split(" -thumb")[0]
        if "-thumb" in parts[1]:
            custom_thumb_url = parts[1].split("-thumb")[1].strip()

    user = message.from_user
    user_name = user.first_name if user else "Unknown"
    user_id = user.id if user else 0

    if user_id != ADMIN_ID:
        active_count = ACTIVE_TASKS.get(user_id, 0)
        if active_count >= USER_TASK_LIMIT:
            await message.reply_text(
                f"⚠️ **Limit Exceeded!**\n\n"
                f"You already have `{active_count}` active downloads running. "
                f"Please wait for them to finish before starting a new one (Max allowed: {USER_TASK_LIMIT})."
            )
            return

    status_msg = await message.reply_text("⏳ Initializing download... Please wait.")
    await process_download(client, status_msg, user_id, user_name, url, 'best', custom_name, custom_thumb_url)

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
        "👇 **Select video format quality:**",
        reply_markup=keyboard
    )

async def process_download(client, status_msg, user_id, user_name, url, quality, custom_name=None, custom_thumb_url=None):
    ACTIVE_TASKS[user_id] = ACTIVE_TASKS.get(user_id, 0) + 1
    
    file_path = None
    auto_thumb_path = None
    temp_custom_thumb = None
    
    try:
        os.makedirs("downloads", exist_ok=True)
        os.makedirs("thumbnails", exist_ok=True)
        last_update_time = 0

        cancel_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✖️ Task Cancel", callback_data=f"cancel_dl_{user_id}")]
        ])

        def download_progress(d):
            nonlocal last_update_time
            if user_id in CANCEL_REQUESTS:
                raise Exception("Task cancelled by user/admin.")

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
                        client.loop.create_task(status_msg.edit_text(progress_str, reply_markup=cancel_keyboard))
                    except Exception:
                        pass

        common_ydl_opts = {
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'max_filesize': 2000 * 1024 * 1024,
            'progress_hooks': [download_progress],
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                }
            },
            'geo_bypass': True,
            'nocheckcertificate': True,
        }

        if quality == 'mp3':
            ydl_opts = {
                **common_ydl_opts,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        elif quality == 'best':
            ydl_opts = {
                **common_ydl_opts,
                'format': 'best',
            }
        else:
            ydl_opts = {
                **common_ydl_opts,
                'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            }

        loop = asyncio.get_running_loop()
        def run_ytdl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info_dict), info_dict

        if user_id in CANCEL_REQUESTS:
            raise Exception("Task cancelled by user/admin.")

        file_path, info_dict = await loop.run_in_executor(None, run_ytdl)
        
        if quality == 'mp3':
            file_path = os.path.splitext(file_path)[0] + ".mp3"
        file_title = info_dict.get('title', 'Media')
        
        if custom_name and file_path and os.path.exists(file_path):
            ext = os.path.splitext(file_path)[1]
            new_file_path = os.path.join("downloads", f"{custom_name}{ext}")
            os.rename(file_path, new_file_path)
            file_path = new_file_path
            file_title = custom_name

        file_size = os.path.getsize(file_path) if file_path and os.path.exists(file_path) else 0

        if user_id in CANCEL_REQUESTS:
            raise Exception("Task cancelled by user/admin.")

        await status_msg.edit_text(
            f"📤 **Uploading...**\n\n" \
            f"📁 **Name:** `{file_title}`\n" \
            f"📦 **Size:** `{human_bytes(file_size)}`",
            reply_markup=cancel_keyboard
        )

        caption = (
            f"<b>{file_title}</b>\n\n" \
            f"👤 <b>Task By:</b> {user_name} (`{user_id}`)\n" \
            f"📦 <b>Size:</b> {human_bytes(file_size)}\n" \
            f"🔗 <b>Link:</b> {url}"
        )

        valid_thumb = None
        if custom_thumb_url:
            temp_custom_thumb = f"thumbnails/custom_{user_id}.jpg"
            success = await download_image_from_url(custom_thumb_url, temp_custom_thumb)
            if success and os.path.exists(temp_custom_thumb):
                valid_thumb = temp_custom_thumb

        if not valid_thumb:
            thumb = USER_THUMBNAILS.get(user_id, None)
            valid_thumb = thumb if thumb and os.path.exists(thumb) else None

        if not valid_thumb and quality != 'mp3' and file_path:
            auto_thumb_path = generate_thumbnail(file_path, user_id)
            valid_thumb = auto_thumb_path

        duration, width, height = 0, 0, 0
        if quality != 'mp3' and file_path and os.path.exists(file_path):
            duration, width, height = get_video_info(file_path)

        if user_id in CANCEL_REQUESTS:
            raise Exception("Task cancelled by user/admin.")

        file_mode = USER_FILE_MODES.get(user_id, "video")

        if quality == 'mp3':
            await asyncio.gather(
                client.send_audio(chat_id=status_msg.chat.id, audio=file_path, caption=caption, thumb=valid_thumb, reply_to_message_id=status_msg.reply_to_message_id),
                client.send_audio(chat_id=DATABASE_CHANNEL_ID, audio=file_path, caption=caption, thumb=valid_thumb)
            )
        elif file_mode == "document":
            await asyncio.gather(
                client.send_document(chat_id=status_msg.chat.id, document=file_path, caption=caption, thumb=valid_thumb, reply_to_message_id=status_msg.reply_to_message_id),
                client.send_document(chat_id=DATABASE_CHANNEL_ID, document=file_path, caption=caption, thumb=valid_thumb)
            )
        else:
            await asyncio.gather(
                client.send_video(chat_id=status_msg.chat.id, video=file_path, caption=caption, duration=duration, width=width, height=height, thumb=valid_thumb, reply_to_message_id=status_msg.reply_to_message_id),
                client.send_video(chat_id=DATABASE_CHANNEL_ID, video=file_path, caption=caption, duration=duration, width=width, height=height, thumb=valid_thumb)
            )

        log_text = (
            f"📥 <b>New Download Completed!</b>\n"
            f"<b>File Name:</b> {file_title}\n"
            f"<b>User:</b> {user_name} (`{user_id}`)"
        )
        try:
            await client.send_message(chat_id=LOG_CHANNEL_ID, text=log_text)
        except Exception:
            pass

    except Exception as e:
        err_msg = str(e)
        if "cancelled" in err_msg.lower():
            await status_msg.edit_text("❌ **Task successfully cancelled!**")
        else:
            await status_msg.edit_text(f"❌ **Download/Upload Failed!**\n\n**Reason:** `{err_msg}`")
    
    finally:
        if user_id in CANCEL_REQUESTS:
            CANCEL_REQUESTS.remove(user_id)
        if user_id in ACTIVE_TASKS:
            ACTIVE_TASKS[user_id] = max(0, ACTIVE_TASKS[user_id] - 1)
        
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        if auto_thumb_path and os.path.exists(auto_thumb_path):
            try:
                os.remove(auto_thumb_path)
            except:
                pass
        if temp_custom_thumb and os.path.exists(temp_custom_thumb):
            try:
                os.remove(temp_custom_thumb)
            except:
                pass

async def main():
    await start_web_server()
    await app.start()
    logging.info("Bot Started Successfully! 🚀")
    await idle()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(main())
