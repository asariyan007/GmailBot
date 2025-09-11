# main.py
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, CallbackQueryHandler, ConversationHandler
)
from database import init_db, save_user, get_user, add_alias, get_latest_alias, remove_user
from gmail_oauth import generate_oauth_link, exchange_code_for_tokens
from gmail_handler import GmailHandler
from utils import get_fernet_from_env, now_ts
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FERNET_KEY = os.getenv("FERNET_KEY")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL") or 5)
ALIAS_RANDOM_LEN = int(os.getenv("ALIAS_RANDOM_LEN") or 6)
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI")   # must include https://
WEBHOOK_URL = os.getenv("WEBHOOK_URL")                # railway root domain

if not TELEGRAM_TOKEN or not FERNET_KEY or not OAUTH_REDIRECT_URI or not WEBHOOK_URL:
    raise RuntimeError("Please set TELEGRAM_TOKEN, FERNET_KEY, OAUTH_REDIRECT_URI, and WEBHOOK_URL in env vars")

fernet = get_fernet_from_env(FERNET_KEY)
gmail_handler = GmailHandler(fernet=fernet, poll_interval=POLL_INTERVAL)
bg_tasks = {}

WAIT_TOKEN = 0

# ---------------- Commands ---------------- #
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔐 Connect Gmail", url=generate_oauth_link(update.message.from_user.id, OAUTH_REDIRECT_URI))]
    ]
    await update.message.reply_text(
        "Welcome! Connect your Gmail to generate temp emails and receive OTPs automatically.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def paste_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    token_code = update.message.text.strip()
    try:
        access_token, refresh_token, email = await exchange_code_for_tokens(token_code)
    except Exception as e:
        await update.message.reply_text(f"Failed to validate token: {e}")
        return ConversationHandler.END
    enc_access = fernet.encrypt(access_token.encode()).decode()
    enc_refresh = fernet.encrypt(refresh_token.encode()).decode()
    await save_user(user_id, email, enc_access, enc_refresh)
    await update.message.reply_text(
        f"Gmail {email} connected successfully!\n\nInline buttons:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Generate Temp Mail", callback_data="generate")],
            [InlineKeyboardButton("🚪 Logout Gmail", callback_data="logout")]
        ])
    )
    if user_id not in bg_tasks:
        loop = asyncio.get_running_loop()
        task = loop.create_task(gmail_handler.poll_user_emails(user_id))
        bg_tasks[user_id] = task
    return ConversationHandler.END

# ---------------- Callback Queries ---------------- #
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "generate":
        user = await get_user(user_id)
        if not user:
            await query.message.reply_text("Please login first using /start.")
            return
        alias = gmail_handler.gen_alias(user['email'], n=ALIAS_RANDOM_LEN)
        ts = now_ts()
        await add_alias(user_id, alias, ts)
        keyboard = [
            [InlineKeyboardButton("📋 Copy", callback_data=f"copy|{alias}")],
            [InlineKeyboardButton("🔁 Change", callback_data=f"change|{alias}")]
        ]
        await query.message.reply_text(f"Generated temp email:\n`{alias}`",
                                       parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("copy|"):
        alias = data.split("|")[1]
        await query.message.reply_text(f"`{alias}`", parse_mode="Markdown")

    elif data.startswith("change|"):
        user = await get_user(user_id)
        alias = gmail_handler.gen_alias(user['email'], n=ALIAS_RANDOM_LEN)
        await add_alias(user_id, alias, now_ts())
        keyboard = [
            [InlineKeyboardButton("📋 Copy", callback_data=f"copy|{alias}")],
            [InlineKeyboardButton("🔁 Change", callback_data=f"change|{alias}")]
        ]
        await query.message.reply_text(f"New temp email:\n`{alias}`",
                                       parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "logout":
        await remove_user(user_id)
        await query.message.reply_text("Logged out successfully! Use /start to login again.")

# ---------------- Main ---------------- #
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, paste_token)],
        states={WAIT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, paste_token)]},
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(callback_handler))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    print("Bot started with webhook")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}"
    )

if __name__ == "__main__":
    main()
