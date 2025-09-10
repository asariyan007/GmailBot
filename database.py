import aiosqlite
from datetime import datetime

DB_FILE = "bot_data.sqlite3"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users(
                tg_id INTEGER PRIMARY KEY,
                email TEXT,
                access_token TEXT,
                refresh_token TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS aliases(
                tg_id INTEGER,
                alias TEXT,
                created_at TEXT,
                PRIMARY KEY(tg_id, alias)
            )
        """)
        await db.commit()

async def save_user(tg_id, email, access_token, refresh_token):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("REPLACE INTO users(tg_id,email,access_token,refresh_token) VALUES (?,?,?,?)",
                         (tg_id,email,access_token,refresh_token))
        await db.commit()

async def get_user(tg_id):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT email, access_token, refresh_token FROM users WHERE tg_id=?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"email": row[0], "access_token": row[1], "refresh_token": row[2]}
            return None

async def remove_user(tg_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM users WHERE tg_id=?", (tg_id,))
        await db.execute("DELETE FROM aliases WHERE tg_id=?", (tg_id,))
        await db.commit()

async def add_alias(tg_id, alias, ts):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR REPLACE INTO aliases(tg_id, alias, created_at) VALUES (?,?,?)",
                         (tg_id, alias, ts))
        await db.commit()

async def get_latest_alias(tg_id):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT alias FROM aliases WHERE tg_id=? ORDER BY created_at DESC LIMIT 1", (tg_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None
