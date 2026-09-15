import os
import time
import asyncio
import logging
import aiohttp
import libtorrent as lt
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)

# --- Configuration ---
API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "your_api_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
ALLOWED_GROUP_ID = int(os.environ.get("ALLOWED_GROUP_ID", "-100123456789"))
DATABASE_CHANNEL_ID = int(os.environ.get("DATABASE_CHANNEL_ID", "-100987654321"))

app = Client("AlluTvSerialsBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

ACTIVE_TASKS = {}
CANCEL_REQUESTS = set()

def human_bytes(size):
    if not size:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"

def get_progress_bar(percentage):
    completed = int(percentage / 10)
    return "█" * completed + "░" * (10 - completed)

# ==========================================
# 1. GOFILE DIRECT DOWNLOAD HANDLER
# ==========================================
async def get_gofile_direct_link(url):
    try:
        file_id = url.split('/')[-1].split('?')[0]
        api_url = f"https://api.gofile.io/contents/{file_id}?wt=4fd6sg3d7s"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    if res_json.get('status') == 'ok':
                        contents = res_json['data']['contents']
                        for _, item in contents.items():
                            if item['type'] == 'file':
                                return item.get('link')
    except Exception as e:
        logging.error(f"GoFile Extraction Error: {e}")
    return None

async def handle_gofile(client, message, status_msg, url):
    await status_msg.edit_text("📥 **Gofile Link Detected!** Fetching direct download link...")
    direct_link = await get_gofile_direct_link(url)
    
    if not direct_link:
        await status_msg.edit_text("❌ Failed to fetch direct link from Gofile.")
        return
        
    user = message.from_user
    await status_msg.edit_text("⏳ Downloading file from Gofile...")
    
    file_path = os.path.join("downloads", f"gofile_{int(time.time())}.mp4")
    os.makedirs("downloads", exist_ok=True)
    
    async with aiohttp.ClientSession() as session:
        async with session.get(direct_link) as resp:
            if resp.status == 200:
                with open(file_path, "wb") as f:
                    while chunk := await resp.content.read(1024 * 1024):
                        f.write(chunk)
                        
                file_size = os.path.getsize(file_path)
                await status_msg.edit_text("📤 Uploading file to Telegram...")
                
                sent_msg = await client.send_document(
                    chat_id=message.chat.id,
                    document=file_path,
                    caption=f"<b>Gofile Downloaded File</b>\n👤 <b>User:</b> {user.first_name} (`{user.id}`)\n📦 <b>Size:</b> {human_bytes(file_size)}"
                )
                try:
                    if sent_msg:
                        await sent_msg.copy(chat_id=DATABASE_CHANNEL_ID)
                except Exception:
                    pass
                os.remove(file_path)
                await status_msg.delete()
                return
    await status_msg.edit_text("❌ Download from Gofile failed.")

# ==========================================
# 2. MAGNET LINK HANDLER
# ==========================================
async def handle_magnet(client, message, status_msg, magnet_link):
    user = message.from_user
    user_id = user.id
    ACTIVE_TASKS[user_id] = ACTIVE_TASKS.get(user_id, 0) + 1
    save_path = "downloads"
    os.makedirs(save_path, exist_ok=True)
    
    ses = lt.session()
    ses.listen_port(6881, 6891)
    ses.add_dht_router("router.bittorrent.com", 6881)
    ses.add_dht_router("router.utorrent.com", 6881)
    ses.add_dht_router("dht.transmissionbt.com", 6881)
    ses.start_dht()
    ses.start_lsd()
    ses.start_upnp()
    ses.start_natpmp()
    
    params = {
        'save_path': save_path,
        'storage_mode': lt.storage_mode_t.storage_mode_sparse
    }
    
    try:
        handle = lt.add_magnet_uri(ses, magnet_link, params)
        handle.set_sequential_download(True)
        
        await status_msg.edit_text("⏳ Fetching torrent metadata from peers (Please wait)...")
        
        timeout = 90
        start_time = time.time()
        while not handle.has_metadata():
            if user_id in CANCEL_REQUESTS:
                raise Exception("Task cancelled by user.")
            if time.time() - start_time > timeout:
                raise Exception("Timeout reached! Could not fetch metadata. Poor seeders/peers.")
            await asyncio.sleep(1)
            
        torrent_name = handle.name()
        await status_msg.edit_text(f"📥 **Starting Torrent Download:**\n`{torrent_name}`")
        
        while handle.status().state != lt.torrent_status.seeding:
            if user_id in CANCEL_REQUESTS:
                raise Exception("Task cancelled by user.")
                
            s = handle.status()
            percentage = s.progress * 100
            bar = get_progress_bar(percentage)
            
            progress_str = (
                f"🧲 **Downloading Magnet...**\n"
                f"📁 <code>{torrent_name}</code>\n\n"
                f"{bar} {percentage:.1f}%\n"
                f" ┣ 💾 **Size:** {human_bytes(s.total_wanted)}\n"
                f" ┣ ⚡ **Speed:** {human_bytes(s.download_rate)}/s\n"
                f" ┗ 👥 **Peers:** {s.num_peers}"
            )
            
            try:
                await status_msg.edit_text(progress_str)
            except Exception:
                pass
                
            await asyncio.sleep(3)
            
        downloaded_file_path = os.path.join(save_path, torrent_name)
        if not os.path.exists(downloaded_file_path):
            raise Exception("Downloaded torrent path not found.")

        file_size = os.path.getsize(downloaded_file_path) if os.path.isfile(downloaded_file_path) else sum(os.path.getsize(os.path.join(path, f)) for path, _, files in os.walk(downloaded_file_path) for f in files)

        caption = (
            f"<b>{torrent_name}</b>\n\n"
            f"👤 <b>Task By:</b> {user.first_name} (`{user_id}`)\n"
            f"📦 <b>Size:</b> {human_bytes(file_size)}\n"
            f"🔗 <b>Type:</b> Magnet Torrent"
        )

        await status_msg.edit_text("📤 Uploading torrent file to Telegram...")
        
        if os.path.isfile(downloaded_file_path):
            sent_msg = await client.send_document(
                chat_id=message.chat.id,
                document=downloaded_file_path,
                caption=caption
            )
            try:
                if sent_msg:
                    await sent_msg.copy(chat_id=DATABASE_CHANNEL_ID)
            except Exception:
                pass
            os.remove(downloaded_file_path)
        else:
            await client.send_message(message.chat.id, f"✅ Torrent Completed: `{torrent_name}`")

        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ **Magnet Task Failed!**\n\n**Reason:** `{str(e)}`")
    finally:
        if user_id in CANCEL_REQUESTS:
            CANCEL_REQUESTS.remove(user_id)
        if user_id in ACTIVE_TASKS:
            ACTIVE_TASKS[user_id] -= 1
            if ACTIVE_TASKS[user_id] <= 0:
                del ACTIVE_TASKS[user_id]

# ==========================================
# 3. TELEGRAM CHANNEL MEDIA HANDLER
# ==========================================
async def handle_telegram_link(client, message, status_msg, link):
    try:
        if "t.me/c/" in link:
            parts = link.split("/c/")
            sub_parts = parts[1].split("/")
            chat_id = int("-100" + sub_parts[0])
            msg_id = int(sub_parts[1].split("?")[0])
        else:
            parts = link.split("t.me/")
            sub_parts = parts[1].split("/")
            chat_id = sub_parts[0]
            msg_id = int(sub_parts[1].split("?")[0])
            
        await status_msg.edit_text("⏳ Fetching message from target channel...")
        target_msg = await client.get_messages(chat_id, msg_id)
        
        if not target_msg or not target_msg.media:
            await status_msg.edit_text("❌ No media found in the provided Telegram link!")
            return
            
        await status_msg.edit_text("📥 Downloading media from Telegram channel...")
        start_time = time.time()
        
        downloaded_file = await target_msg.download(
            file_name="downloads/",
            progress=progress_for_telegram,
            progress_args=(client, status_msg, "📥 **Downloading from Telegram:**", start_time)
        )
        
        file_size = os.path.getsize(downloaded_file)
        await status_msg.edit_text("📤 Uploading media to chat & database...")
        
        user = message.from_user
        caption = (
            f"<b>Leeched Telegram Media</b>\n\n"
            f"👤 <b>Requested By:</b> {user.first_name} (`{user.id}`)\n"
            f"📦 <b>Size:</b> {human_bytes(file_size)}"
        )
        
        sent_msg = await client.send_document(
            chat_id=message.chat.id,
            document=downloaded_file,
            caption=caption
        )
        
        try:
            if sent_msg:
                await sent_msg.copy(chat_id=DATABASE_CHANNEL_ID)
        except Exception:
            pass
            
        os.remove(downloaded_file)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ **Telegram Leech Failed!**\n\n**Reason:** `{str(e)}`")

async def progress_for_telegram(current, total, client, status_msg, text, start_time):
    now = time.time()
    diff = now - start_time
    if round(diff % 5.0) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = (total - current) / speed if speed > 0 else 0
        progress_str = (
            f"{text}\n\n"
            f"{get_progress_bar(percentage)} {percentage:.1f}%\n"
            f" ┣ 🚀 **Speed:** {human_bytes(speed)}/s\n"
            f" ┣ ⏱️ **ETA:** {int(eta)}s\n"
            f" ┗ 💾 **Done:** {human_bytes(current)} / {human_bytes(total)}"
        )
        try:
            await status_msg.edit_text(progress_str)
        except Exception:
            pass

# ==========================================
# UNIFIED /leech COMMAND ROUTER
# ==========================================
@app.on_message(filters.command("leech") & filters.chat(ALLOWED_GROUP_ID))
async def universal_leech_handler(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply_text(
            "⚠️ **Please provide a link after /leech!**\n\n"
            "**Examples:**\n"
            "• `/leech magnet:?xt=...`\n"
            "• `/leech https://gofile.io/d/...`\n"
            "• `/leech https://t.me/...`"
        )
        return
        
    input_text = args[1]
    status_msg = await message.reply_text("🔍 **Analyzing your link...**")
    
    if input_text.startswith("magnet:?xt="):
        await handle_magnet(client, message, status_msg, input_text)
    elif "gofile.io/d/" in input_text:
        await handle_gofile(client, message, status_msg, input_text)
    elif "t.me/" in input_text:
        await handle_telegram_link(client, message, status_msg, input_text)
    else:
        await status_msg.edit_text("❌ **Unsupported link format!** Please provide a valid Magnet, Gofile, or Telegram link.")

# --- Run Bot ---
if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
