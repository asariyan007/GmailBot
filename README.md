# Telegram Temp Gmail Bot

This bot creates Gmail alias addresses (e.g. `you+abc123@gmail.com`), monitors inbox, and forwards only one OTP per generated alias to the Telegram user.

> **IMPORTANT:** Gmail requires either OAuth2 or App Passwords for IMAP login. This project assumes you will use **App Password**. Create an app password in Google Account > Security > App passwords and use that as password when logging in.

## Features
- `/start` → Login via inline button (provide Gmail and App Password)
- `/generate` → Creates a new alias (username+random@domain)
- Inline buttons for Copy and Change Mail
- Auto-polls Gmail inbox and sends the first OTP matching the alias
- SQLite persistent DB

## Setup
1. Clone repo to GitHub.
2. In Railway (or local), set environment variables:
   - `TELEGRAM_TOKEN` — your bot token
   - `FERNET_KEY` — `Fernet.generate_key().decode()` (generate locally)
   - (optional) `POLL_INTERVAL`, `ALIAS_RANDOM_LEN`
3. Deploy to Railway. Add `Procfile` as shown.

## Security notes
- The bot stores app passwords encrypted using Fernet; **keep FERNET_KEY secret**.
- Do not reuse Google main password here — use App Passwords only.
- If anyone else can access your Railway/host env vars, they can decrypt stored passwords.

## Deploy tips
- For scale, convert to webhooks (faster) and use a worker for IMAP polling; or manage background tasks via a job queue.
- If Gmail blocks app password in future, you must switch to OAuth2 flow.
