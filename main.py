# main.py
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from database import init_db, save_user, get_user, add_alias, get_latest_alias
from gmail_handler import GmailHandler
from utils import get_fernet_from_env, now_ts
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FERNET_KEY = os.getenv("FERNET_KEY")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL") or 5)
ALIAS_RANDOM_LEN = int(os.getenv("ALIAS_RANDOM_LEN") or 6)

if not TELEGRAM_TOKEN or not FERNET_KEY:
    raise RuntimeError("Please set TELEGRAM_TOKEN and FERNET_KEY in env vars")

fernet = get_fernet_from_env(FERNET_KEY)

# conversation states
ASK_EMAIL, ASK_PASSWORD = range(2)

gmail_handler = GmailHandler(fernet=fernet, poll_interval=POLL_INTERVAL)

# keep track of background tasks per user
bg_tasks = {}

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔐 Login", callback_data="login")]]
    await update.message.reply_text("Welcome. Use Login to store your Gmail (App password recommended).", reply_markup=InlineKeyboardMarkup(keyboard))

async def login_button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Send your Gmail address (e.g. example@gmail.com):")
    return ASK_EMAIL

async def ask_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    context.user_data['tmp_email'] = email
    await update.message.reply_text("Now send the App Password (16-character Gmail App Password). It will be stored encrypted.")
    return ASK_PASSWORD

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pw = update.message.text.strip()
    email = context.user_data.get('tmp_email')
    if not email:
        await update.message.reply_text("Email missing. Send /start and try again.")
        return ConversationHandler.END
    # encrypt password
    enc_pw = fernet.encrypt(pw.encode()).decode()
    tg_id = update.message.from_user.id
    await save_user(tg_id, email, enc_pw)
    await update.message.reply_text("Login stored successfully! You can now /generate alias.")
    # start background IMAP poller if not running
    if tg_id not in bg_tasks:
        # create task
        loop = asyncio.get_event_loop()
        task = loop.create_task(run_user_poll(tg_id))
        bg_tasks[tg_id] = task
    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.message.from_user.id
    user = await get_user(tg_id)
    if not user:
        await update.message.reply_text("You are not logged in. Use /start and Login first.")
        return
    base_email = user['email']
    # generate alias
    alias = gmail_handler.gen_alias(base_email, n=ALIAS_RANDOM_LEN)
    ts = now_ts()
    await add_alias(tg_id, alias, ts)
    # keyboard with Copy and Change
    keyboard = [
        [InlineKeyboardButton("📋 Copy (send in chat)", callback_data=f"copy|{alias}")],
        [InlineKeyboardButton("🔁 Change Mail", callback_data=f"change|{alias}")]
    ]
    await update.message.reply_text(f"Generated alias:\n`{alias}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    # ensure background poller running
    if tg_id not in bg_tasks:
        loop = asyncio.get_event_loop()
        task = loop.create_task(run_user_poll(tg_id))
        bg_tasks[tg_id] = task

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("copy|"):
        alias = data.split("|",1)[1]
        # send alias plainly so user can copy
        await query.message.reply_text(f"`{alias}`", parse_mode="Markdown")
    elif data.startswith("change|"):
        # simply generate a new one
        tg_id = query.from_user.id
        user = await get_user(tg_id)
        if not user:
            await query.message.reply_text("Not logged in.")
            return
        alias = gmail_handler.gen_alias(user['email'], n=ALIAS_RANDOM_LEN)
        await add_alias(tg_id, alias, now_ts())
        keyboard = [
            [InlineKeyboardButton("📋 Copy (send in chat)", callback_data=f"copy|{alias}")],
            [InlineKeyboardButton("🔁 Change Mail", callback_data=f"change|{alias}")]
        ]
        await query.message.reply_text(f"New alias:\n`{alias}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def run_user_poll(tg_id: int):
    """
    Ensure db init done before calling.
    This coroutine will try to pull user's stored password and keep a polling loop via gmail_handler.
    """
    # small delay to let bot start
    await asyncio.sleep(1)
    from database import get_user
    user = await get_user(tg_id)
    if not user:
        return
    enc_pw = user['enc_password']
    try:
        app_pw = fernet.decrypt(enc_pw.encode()).decode()
    except Exception:
        return
    email_addr = user['email']
    # pass a lightweight bot-like object to gmail_handler for sending messages
    from telegram import Bot
    bot = Bot(token=TELEGRAM_TOKEN)
    await gmail_handler.fetch_and_process(tg_id, email_addr, app_pw, bot)

async def on_startup(app):
    # init db
    await init_db()
    # start background pollers for already-logged users (if running from persistent filesystem)
    # optionally: query all users and start pollers
    import aiosqlite
    async with aiosqlite.connect("bot_data.sqlite3") as db:
        cur = await db.execute("SELECT tg_id FROM users")
        rows = await cur.fetchall()
        loop = asyncio.get_event_loop()
        for r in rows:
            tg = r[0]
            if tg not in bg_tasks:
                task = loop.create_task(run_user_poll(tg))
                bg_tasks[tg] = task

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_button_cb, pattern="^login$")],
        states={
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_email)],
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(conv)
    app.add_handler(CommandHandler("generate", generate_cmd))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    # run startup
    app.post_init.append(on_startup)

    print("Bot started")
    app.run_polling()
if __name__ == "__main__":
    main()
