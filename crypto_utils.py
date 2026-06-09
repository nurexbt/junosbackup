"""
Symmetric encryption for stored SSH passwords using Fernet (AES-128-CBC + HMAC).
The key is derived from SECRET_KEY env var and stored in .fernet_key on first run.
"""
import os
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_KEY_FILE = Path('.fernet_key')
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet:
        return _fernet

    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes().strip()
    else:
        # Derive a stable key from SECRET_KEY so passwords survive restarts
        secret = os.environ.get('SECRET_KEY', 'change-me-in-production').encode()
        salt   = b'juniper_cm_salt_v1'
        kdf    = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                             salt=salt, iterations=480_000)
        key = base64.urlsafe_b64encode(kdf.derive(secret))
        _KEY_FILE.write_bytes(key)
        _KEY_FILE.chmod(0o600)

    _fernet = Fernet(key)
    return _fernet


def encrypt_password(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_password(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
