# database.py
import aiosqlite
import asyncio
from typing import Optional, List, Dict

DB_PATH = "bot_data.sqlite3"

CREATE_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        email TEXT,
        enc_password TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER,
        alias_email TEXT,
        created_at INTEGER,
        used_one_otp INTEGER DEFAULT 0,
        FOREIGN KEY(tg_id) REFERENCES users(tg_id)
    )""",
    """CREATE TABLE IF NOT EXISTS processed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alias_email TEXT,
        mail_uid TEXT UNIQUE,
        created_at INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS otps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER,
        alias_email TEXT,
        otp_text TEXT,
        received_at INTEGER
    )"""
]

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in CREATE_STATEMENTS:
            await db.execute(stmt)
        await db.commit()

# user functions

async def save_user(tg_id: int, email: str, enc_password: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("REPLACE INTO users (tg_id, email, enc_password) VALUES (?, ?, ?)",
                         (tg_id, email, enc_password))
        await db.commit()

async def get_user(tg_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT tg_id, email, enc_password FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if not row: return None
        return {"tg_id": row[0], "email": row[1], "enc_password": row[2]}

# alias functions

async def add_alias(tg_id: int, alias_email: str, created_at: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO aliases (tg_id, alias_email, created_at) VALUES (?, ?, ?)",
                         (tg_id, alias_email, created_at))
        await db.commit()

async def get_latest_alias(tg_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, alias_email, used_one_otp FROM aliases WHERE tg_id = ? ORDER BY id DESC LIMIT 1", (tg_id,))
        row = await cur.fetchone()
        if not row: return None
        return {"id": row[0], "alias_email": row[1], "used_one_otp": row[2]}

async def mark_alias_used(alias_email: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE aliases SET used_one_otp = 1 WHERE alias_email = ?", (alias_email,))
        await db.commit()

# processed mail uids to avoid duplicates

async def is_processed(mail_uid: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM processed WHERE mail_uid = ? LIMIT 1", (mail_uid,))
        row = await cur.fetchone()
        return bool(row)

async def mark_processed(alias_email: str, mail_uid: str, created_at: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO processed (alias_email, mail_uid, created_at) VALUES (?, ?, ?)",
                         (alias_email, mail_uid, created_at))
        await db.commit()

# OTP storage

async def add_otp(tg_id: int, alias_email: str, otp_text: str, received_at: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO otps (tg_id, alias_email, otp_text, received_at) VALUES (?, ?, ?, ?)",
                         (tg_id, alias_email, otp_text, received_at))
        await db.commit()
