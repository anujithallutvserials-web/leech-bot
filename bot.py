import os
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import yt_dlp

# ലോങ്ങിങ് സെറ്റപ്പ്
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

# ഗ്രൂപ്പിലെ അഡ്മിൻ ആണോ എന്ന് പരിശോധിക്കാനുള്ള ഫങ്ഷൻ
async def is_admin(client: Client, chat_id: int, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in ["creator", "administrator"]
    except Exception:
        return False

# 1. /usetting കമാൻഡ് (തംബ്‌നെയിൽ സെറ്റ് ചെയ്യാൻ)
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
        "നിങ്ങളുടെ ഡൗൺലോഡുകൾക്കായുള്ള തംബ്‌നെയിൽ ഇവിടെ ക്രമീകരിക്കാം:",
        reply_markup=keyboard
    )

@app.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if data == "set_thumb":
        WAITING_FOR_THUMB.add(user_id)
        await callback_query.message.edit_text(
            "🖼️ ദയവായി നിങ്ങളുടെ പുതിയ തംബ്‌നെയിൽ ഫോട്ടോ (Image) ഈ ഗ്രൂപ്പിലേക്ക് അയക്കുക.\n"
            "അത് ബോട്ട് ഓട്ടോമാറ്റിക്കായി തംബ്‌നെയിൽ ആയി സേവ് ചെയ്തുകൊള്ളും!"
        )
    elif data == "remove_thumb":
        if user_id in USER_THUMBNAILS:
            if os.path.exists(USER_THUMBNAILS[user_id]):
                os.remove(USER_THUMBNAILS[user_id])
            del USER_THUMBNAILS[user_id]
        if user_id in WAITING_FOR_THUMB:
            WAITING_FOR_THUMB.remove(user_id)
            
        await callback_query.message.edit_text("🗑️ നിങ്ങളുടെ തംബ്‌നെയിൽ വിജയകരമായി നീക്കം ചെയ്തിരിക്കുന്നു!")

@app.on_message(filters.photo & filters.chat(ALLOWED_GROUP_ID))
async def save_thumbnail(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in WAITING_FOR_THUMB:
        os.makedirs("thumbnails", exist_ok=True)
        photo_path = f"thumbnails/{user_id}.jpg"
        await message.download(file_name=photo_path)
        USER_THUMBNAILS[user_id] = photo_path
        WAITING_FOR_THUMB.remove(user_id)
        await message.reply_text("✅ തംബ്‌നെയിൽ വിജയകരമായി സേവ് ചെയ്യപ്പെട്ടിരിക്കുന്നു!")

# 2. /v കമാൻഡ് (അഡ്മിൻമാർക്ക് മാത്രം വെരിഫിക്കേഷൻ ലിങ്ക് ബൈപാസ് ചെയ്യാൻ)
@app.on_message(filters.command("v") & filters.chat(ALLOWED_GROUP_ID))
async def bypass_handler(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not await is_admin(client, message.chat.id, user_id):
        await message.reply_text("❌ ഈ കമാൻഡ് ഉപയോഗിക്കാൻ **അഡ്മിൻമാർക്ക്** മാത്രമേ അനുവാദമുള്ളൂ!")
        return

    if len(message.command) < 2:
        await message.reply_text("❌ ദയവായി വെരിഫിക്കേഷൻ ലിങ്ക് നൽകുക!\nഉദാഹരണത്തിന്: `/v https://vplink.in/xxxx`")
        return

    url = message.command[1]
    msg = await message.reply_text("🔍 ലിങ്ക് പരിശോധിക്കുന്നു... ദയവായി കാത്തിരിക്കുക.")

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
        await msg.edit_text(f"❌ ലിങ്ക് ബൈപാസ് ചെയ്യുന്നത് പരാജയപ്പെട്ടു!\n\n**കാരണം:** `{str(e)}`")

# 3. /leech കമാൻഡ്
@app.on_message(filters.command("leech") & filters.chat(ALLOWED_GROUP_ID))
async def leech_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ ദയവായി ഒരു ലിങ്ക് നൽകുക!\nഉദാഹരണത്തിന്: `/leech https://link.com`")
        return

    url = message.command[1]
    user = message.from_user
    user_name = user.first_name if user else "Unknown"
    user_id = user.id if user else 0

    status_msg = await message.reply_text("⏳ ഡൗൺലോഡ് ആരംഭിക്കുന്നു... ദയവായി കാത്തിരിക്കുക.")

    file_path = None
    try:
        os.makedirs("downloads", exist_ok=True)

        ydl_opts = {
            'format': 'best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'max_filesize': 2000 * 1024 * 1024,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            file_title = info_dict.get('title', 'Video')

        await status_msg.edit_text("📤 ടെലഗ്രാമിലേക്ക് അപ്‌ലോഡ് ചെയ്യുന്നു...")

        caption = (
            f"<b>{file_title}</b>\n\n"
            f"👤 <b>Task By:</b> {user_name} (`{user_id}`)\n"
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
            f"📁 <b>File:</b> {file_title}"
        )
        await client.send_message(chat_id=LOG_CHANNEL_ID, text=log_text)

        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ ഡൗൺലോഡ് പരാജയപ്പെട്ടു!\n\n**കാരണം:** `{str(e)}`")
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

if __name__ == "__main__":
    print("🤖 ലിച്ച് ബൂട്ട് വിജയകരമായി സ്റ്റാർട്ട് ചെയ്തു...")
    app.run()

