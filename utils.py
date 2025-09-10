from cryptography.fernet import Fernet
import time
import os

def get_fernet_from_env(key):
    return Fernet(key.encode())

def now_ts():
    return str(int(time.time()))
