# main.py
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, CallbackQueryHandler, ConversationHandler
)
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

from database import init_db, save_user, get_user, add_alias, remove_user
from gmail_oauth import generate_oauth_link, exchange_code_for_tokens
from gmail_handler import GmailHandler
from utils import get_fernet_from_env, now_ts
from dotenv import load_dotenv

load_dotenv()

# ---------------- Config ---------------- #
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FERNET_KEY = os.getenv("FERNET_KEY")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL") or 5)
ALIAS_RANDOM_LEN = int(os.getenv("ALIAS_RANDOM_LEN") or 6)
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")   # e.g. https://xxx.up.railway.app
PORT = int(os.getenv("PORT", 8000))

if not TELEGRAM_TOKEN or not FERNET_KEY or not OAUTH_REDIRECT_URI or not WEBHOOK_URL:
    raise RuntimeError("❌ Please set TELEGRAM_TOKEN, FERNET_KEY, OAUTH_REDIRECT_URI, and WEBHOOK_URL in env vars")

fernet = get_fernet_from_env(FERNET_KEY)
gmail_handler = GmailHandler(fernet=fernet, poll_interval=POLL_INTERVAL)
bg_tasks = {}
WAIT_TOKEN = 0

# ---------------- Handlers ---------------- #
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

    # background polling
    if user_id not in bg_tasks:
        loop = asyncio.get_running_loop()
        task = loop.create_task(gmail_handler.poll_user_emails(user_id))
        bg_tasks[user_id] = task

    return ConversationHandler.END

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

# ---------------- Init Telegram App ---------------- #
telegram_app: Application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

conv = ConversationHandler(
    entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, paste_token)],
    states={WAIT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, paste_token)]},
    fallbacks=[]
)

telegram_app.add_handler(CommandHandler("start", start_cmd))
telegram_app.add_handler(conv)
telegram_app.add_handler(CallbackQueryHandler(callback_handler))

# ---------------- FastAPI (with lifespan) ---------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await telegram_app.initialize()
    # webhook set (token included in path)
    await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
    print(f"🚀 Bot started with webhook at {WEBHOOK_URL}/{TELEGRAM_TOKEN}")
    yield
    await telegram_app.stop()
    await telegram_app.shutdown()

fastapi_app = FastAPI(lifespan=lifespan)

# Telegram webhook endpoint
@fastapi_app.post(f"/{TELEGRAM_TOKEN}")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}

# Gmail OAuth callback
@fastapi_app.get("/oauth/callback")
async def oauth_callback(request: Request):
    params = request.query_params
    code = params.get("code")
    if not code:
        return {"error": "No code in callback"}
    try:
        access_token, refresh_token, email = await exchange_code_for_tokens(code)
        enc_access = fernet.encrypt(access_token.encode()).decode()
        enc_refresh = fernet.encrypt(refresh_token.encode()).decode()
        return {"status": "ok", "email": email}
    except Exception as e:
        return {"error": str(e)}
