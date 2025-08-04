# main.py - Professional All-in-One Bot Script for Heroku

import os
import dropbox
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. PROFESSIONAL LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 2. SECURE CONFIGURATION LOADING FROM HEROKU CONFIG VARS ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
DROPBOX_APP_KEY = os.environ.get('DROPBOX_APP_KEY')
DROPBOX_APP_SECRET = os.environ.get('DROPBOX_APP_SECRET')
DROPBOX_REFRESH_TOKEN = os.environ.get('DROPBOX_REFRESH_TOKEN') # This is optional at first

# --- 3. FLASK WEB SERVER (To Satisfy Heroku's Web Dyno Requirement If Needed) ---
app = Flask('')

@app.route('/')
def home():
    return "✅ Professional Dropbox Bot is alive."

def run_web_server():
    # Heroku provides the port dynamically
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# --- 4. CORE BOT FUNCTIONALITY ---

def get_dbx_client():
    """Initializes and returns a Dropbox client, handling authentication errors."""
    if not DROPBOX_REFRESH_TOKEN:
        raise ValueError("CRITICAL: Dropbox Refresh Token is not configured in Heroku Config Vars.")
    try:
        dbx = dropbox.Dropbox(
            app_key=DROPBOX_APP_KEY,
            app_secret=DROPBOX_APP_SECRET,
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN
        )
        dbx.users_get_current_account() # Test if the token is valid
        return dbx
    except dropbox.exceptions.AuthError as e:
        logger.error(f"Dropbox AuthError: {e}. The Refresh Token is likely invalid or expired.")
        raise ValueError("The Dropbox Refresh Token is invalid. Please use /start to re-authenticate.")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets user and provides authentication steps if not configured."""
    user = update.effective_user
    if DROPBOX_REFRESH_TOKEN:
        await update.message.reply_html(
            f"Hello {user.mention_html()}! I am fully configured and ready."
        )
    else:
        # Generate the auth URL for the user to get a new code
        auth_flow = dropbox.DropboxOAuth2Flow(
            consumer_key=DROPBOX_APP_KEY, consumer_secret=DROPBOX_APP_SECRET,
            token_access_type='offline', redirect_uri=None, session=None, csrf_token_session_key=None
        )
        auth_url = auth_flow.start()
        await update.message.reply_html(
            f"Hello {user.mention_html()}! <b>Welcome to the one-time setup.</b>\n\n"
            f"1. Click here to authorize the bot: <a href='{auth_url}'><b>Authorize Now</b></a>\n"
            f"2. Click 'Allow' and copy the unique code Dropbox gives you.\n"
            f"3. Send the code back to me like this: `/auth YOUR_CODE`"
        )

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receives the auth code and generates the final Refresh Token."""
    if not context.args:
        await update.message.reply_text("Usage: /auth <authorization_code>")
        return
    
    try:
        auth_code = context.args[0].strip()
        auth_flow = dropbox.DropboxOAuth2Flow(
            consumer_key=DROPBOX_APP_KEY, consumer_secret=DROPBOX_APP_SECRET,
            redirect_uri=None, session=None, csrf_token_session_key=None
        )
        oauth_result = auth_flow.finish(auth_code)
        new_refresh_token = oauth_result.refresh_token

        await update.message.reply_html(
            "✅ <b>SUCCESS!</b> Here is your permanent Refresh Token.\n\n"
            "<b>FINAL STEP:</b> You must now add this token to Heroku. Go to your terminal and run:\n"
            "`heroku config:set DROPBOX_REFRESH_TOKEN=THE_TOKEN_BELOW`\n\n"
            "Copy the token now:"
        )
        await update.message.reply_text(f"`{new_refresh_token}`", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Auth command error: {e}")
        await update.message.reply_text("❌ Authentication failed. Please try /start again.")

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The main handler to process files."""
    if not DROPBOX_REFRESH_TOKEN:
        await update.message.reply_text("Bot not configured. Please use /start for setup.")
        return

    file_to_process = update.message.video or update.message.document
    if not file_to_process:
        return

    original_file_name = file_to_process.file_name or f"video_{file_to_process.file_unique_id}.mp4"
    msg = await update.message.reply_text(f"Processing '{original_file_name}'...")

    try:
        dbx = get_dbx_client()
        file_object = await file_to_process.get_file()
        file_content_bytes = await file_object.download_as_bytearray()
        
        dropbox_path = f'/Heroku Uploads/{original_file_name}'
        await msg.edit_text(f"Uploading to Dropbox...")
        
        dbx.files_upload(bytes(file_content_bytes), dropbox_path, mode=dropbox.files.WriteMode('overwrite'))
        
        await msg.edit_text("Creating direct streaming link...")
        shared_link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_path)
        direct_stream_link = shared_link_metadata.url.replace('?dl=0', '?raw=1')
        
        await msg.edit_text(
            f"✅ **Upload Complete!**\n\n"
            f"**File:** `{original_file_name}`\n"
            f"**Direct Link:** `{direct_stream_link}`",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )

    except ValueError as e: # Catches specific auth errors
        await msg.edit_text(f"❌ Auth Error: {e}")
    except Exception as e:
        logger.error(f"Media handler error: {e}", exc_info=True)
        await msg.edit_text("❌ A critical error occurred. Check the logs.")

def main_bot():
    """Initializes and runs the Telegram bot."""
    if not all([TELEGRAM_TOKEN, DROPBOX_APP_KEY, DROPBOX_APP_SECRET]):
        logger.critical("FATAL: Essential bot configurations are missing from Heroku Config Vars.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("auth", auth_command))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, media_handler))
    
    logger.info("Bot is starting to poll...")
    application.run_polling()

if __name__ == '__main__':
    # Start Flask server in a background thread for UptimeRobot
    web_server_thread = threading.Thread(target=run_web_server)
    web_server_thread.daemon = True
    web_server_thread.start()
    
    # Start the main bot
    main_bot()
