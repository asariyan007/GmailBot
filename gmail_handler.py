import asyncio
import random
import string
from googleapiclient.discovery import build
from database import get_user

class GmailHandler:
    def __init__(self, fernet, poll_interval=5):
        self.fernet = fernet
        self.poll_interval = poll_interval
        self.user_tasks = {}

    def gen_alias(self, email, n=6):
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))
        local, domain = email.split("@")
        return f"{local}+{random_str}@{domain}"

    async def poll_user_emails(self, tg_id):
        while True:
            user = await get_user(tg_id)
            if not user:
                break
            access_token = self.fernet.decrypt(user['access_token'].encode()).decode()
            creds = type('Obj', (), {"token": access_token})()
            service = build('gmail', 'v1', credentials=creds)
            # TODO: fetch OTPs from Gmail messages using Gmail API
            await asyncio.sleep(self.poll_interval)
