# gmail_handler.py
import random
import string
import time
import re
import asyncio
from cryptography.fernet import Fernet
import aioimaplib
import email
from email.header import decode_header
from typing import Optional
from database import is_processed, mark_processed, add_otp, mark_alias_used, get_latest_alias
from utils import now_ts

# OTP regex: common patterns 4-8 digits (adjust if needed)
OTP_REGEX = re.compile(r"\b(\d{4,8})\b")

class GmailHandler:
    def __init__(self, fernet: Fernet, poll_interval: int = 5):
        self.fernet = fernet
        self.poll_interval = poll_interval
        self.sessions = {}  # cache IMAP sessions per user tg_id to reuse

    def gen_alias(self, base_email: str, n: int = 6) -> str:
        # support username+random@gmail.com
        if "@" not in base_email:
            raise ValueError("Invalid email")
        user, domain = base_email.split("@", 1)
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
        return f"{user}+{rand}@{domain}"

    async def connect_imap(self, email_addr: str, app_password: str) -> aioimaplib.IMAP4_SSL:
        client = aioimaplib.IMAP4_SSL(host='imap.gmail.com', port=993)
        await client.wait_hello_from_server()
        await client.login(email_addr, app_password)
        await client.select("INBOX")
        return client

    async def fetch_and_process(self, tg_id: int, email_addr: str, app_password: str, bot):
        """
        Main loop per logged-in user. Polls inbox and sends new OTPs that match latest alias and haven't been used.
        """
        # Keep a connection alive. Reconnect on errors.
        while True:
            try:
                client = await self.connect_imap(email_addr, app_password)
                # search for UNSEEN or ALL mails and process
                typ, data = await client.search('ALL')
                if typ != 'OK':
                    await client.logout()
                    await asyncio.sleep(self.poll_interval)
                    continue
                uids = data[0].split()
                # iterate newest first
                for uid in reversed(uids):
                    uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                    already = await is_processed(uid_str)
                    if already:
                        continue
                    # fetch body
                    typ, fetched = await client.fetch(uid_str, '(RFC822)')
                    if typ != 'OK':
                        continue
                    raw = b""
                    for part in fetched[0]:
                        if isinstance(part, bytes):
                            raw += part
                    try:
                        msg = email.message_from_bytes(raw)
                    except Exception:
                        continue
                    # decode subject + body to text
                    subj = self._decode_header(msg.get("Subject", ""))
                    body = self._get_text_from_msg(msg)
                    text = f"{subj}\n\n{body}"
                    # check for latest alias for this user
                    latest_alias = await get_latest_alias(tg_id)
                    if not latest_alias:
                        # no alias generated yet
                        await mark_processed("", uid_str, now_ts())
                        continue
                    alias_email = latest_alias['alias_email']
                    # make sure the mail is for that alias — check To: header
                    to_header = msg.get_all('To', [])
                    to_text = " ".join(str(x) for x in to_header)
                    if alias_email not in to_text:
                        # not for our current alias — skip but mark processed to avoid reprocessing
                        await mark_processed(alias_email, uid_str, now_ts())
                        continue
                    # find OTP
                    m = OTP_REGEX.search(text)
                    if not m:
                        await mark_processed(alias_email, uid_str, now_ts())
                        continue
                    otp = m.group(1)
                    # ensure alias hasn't already used a otp (only one allowed per alias)
                    if latest_alias.get('used_one_otp'):
                        await mark_processed(alias_email, uid_str, now_ts())
                        continue
                    # send OTP to telegram
                    await add_otp(tg_id, alias_email, otp, now_ts())
                    # mark processed & alias used
                    await mark_processed(alias_email, uid_str, now_ts())
                    await mark_alias_used(alias_email)
                    # send via bot
                    try:
                        txt = f"✅ New OTP for `{alias_email}`:\n`{otp}`\n\nSource subject: {subj}"
                        await bot.send_message(chat_id=tg_id, text=txt, parse_mode="Markdown")
                    except Exception:
                        pass
                await client.logout()
            except Exception as e:
                # reconnect later
                # print("IMAP error:", e)
                await asyncio.sleep(self.poll_interval)
            await asyncio.sleep(self.poll_interval)

    def _decode_header(self, header_val):
        try:
            decoded = decode_header(header_val)
            parts = []
            for part, enc in decoded:
                if isinstance(part, bytes):
                    try:
                        parts.append(part.decode(enc or "utf-8", errors="ignore"))
                    except:
                        parts.append(part.decode("utf-8", errors="ignore"))
                else:
                    parts.append(part)
            return " ".join(parts)
        except Exception:
            return header_val or ""

    def _get_text_from_msg(self, msg):
        # prefer text/plain
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disp = str(part.get('Content-Disposition'))
                if ctype == 'text/plain' and 'attachment' not in disp:
                    try:
                        return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                    except:
                        return str(part.get_payload(decode=True))
            # fallback to html
            for part in msg.walk():
                if part.get_content_type() == 'text/html':
                    try:
                        return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                    except:
                        return str(part.get_payload(decode=True))
            return ""
        else:
            try:
                return msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
            except:
                return str(msg.get_payload(decode=True))
