import os
import yt_dlp
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# കുക്കീസ് ഫയലിന്റെ പാത്ത്
COOKIE_FILE = "cookies.txt"

# യൂട്യൂബ് ലിങ്ക് നേരിട്ട് അയക്കുമ്പോൾ (അല്ലെങ്കിൽ /youtube എന്ന് കൊടുക്കുമ്പോൾ) വർക്ക് ചെയ്യാൻ
@app.on_message(filters.regex(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/.+") | filters.command("youtube"))
async def youtube_download_handler(client, message):
    # കമാൻഡ് ആണെങ്കിൽ ലിങ്ക് എടുക്കുക, അല്ലെങ്കിൽ നേരിട്ട് അയച്ച ടെക്സ്റ്റ് എടുക്കുക
    url = message.text.split(" ")[1] if len(message.command) > 2 else message.text.strip()
    
    if not url.startswith("http"):
        return

    # ചിത്രത്തിൽ കണ്ടതുപോലെ ഓരോ ക്വാളിറ്റി ബട്ടണും താഴെ താഴെയായി (Row by Row) ക്രമീകരിക്കുന്നു
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 144p", callback_data=f"dl|144|{url}")],
        [InlineKeyboardButton("🎬 240p", callback_data=f"dl|240|{url}")],
        [InlineKeyboardButton("🎬 360p", callback_data=f"dl|360|{url}")],
        [InlineKeyboardButton("🎬 480p", callback_data=f"dl|480|{url}")],
        [InlineKeyboardButton("🎬 720p", callback_data=f"dl|720|{url}")],
        [InlineKeyboardButton("🎬 1080p", callback_data=f"dl|1080|{url}")],
        [InlineKeyboardButton("🎵 MP3 Audio", callback_data=f"dl|mp3|{url}")]
    ])

    await message.reply_text("യൂട്യൂബ് ലിങ്ക് ലഭിച്ചു! താഴെ കാണുന്ന ക്വാളിറ്റി ഓപ്ഷനുകളിൽ നിന്നും ഒരെണ്ണം തിരഞ്ഞെടുക്കുക:", reply_markup=keyboard)


# ബട്ടൺ ക്ലിക്ക് ചെയ്യുമ്പോൾ ഡൗൺലോഡ് ചെയ്ത് അയക്കുന്ന കോഡ്
@app.on_callback_query(filters.regex("^dl\\|"))
async def button_download_callback(client, callback_query):
    data = callback_query.data.split("|")
    quality = data[1]
    url = data[2]

    await callback_query.message.edit_text("⏳ ഡൗൺലോഡ് ചെയ്യുന്നു, ദയവായി കാത്തിരിക്കുക...")

    try:
        ydl_opts = {
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'outtmpl': '%(title)s.%(ext)s',
        }

        if quality == "mp3":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            ydl_opts['format'] = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if quality == "mp3":
                filename = filename.rsplit(".", 1)[0] + ".mp3"

        # ടെലഗ്രാമിലേക്ക് ഫയൽ അയച്ചു കൊടുക്കുന്നു
        await callback_query.message.reply_document(document=filename, caption="ഇതാ നിങ്ങളുടെ ഫയൽ! 🎉")
        
        # ഫോൾഡറിൽ നിന്നും ഫയൽ ഒഴിവാക്കുന്നു
        if os.path.exists(filename):
            os.remove(filename)
            
        await callback_query.message.delete()

    except Exception as e:
        await callback_query.message.edit_text(f"❌ ഡൗൺലോഡ് ചെയ്യുന്നതിൽ പരാജയപ്പെട്ടു!\n\n**കാരണം:** `{str(e)}`")
