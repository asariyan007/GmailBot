# utils.py
import os
import time
from cryptography.fernet import Fernet

def now_ts():
    return int(time.time())

def get_fernet_from_env(key: str):
    return Fernet(key.encode())
