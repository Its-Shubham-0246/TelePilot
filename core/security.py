import base64
from cryptography.fernet import Fernet
from config import settings


def _get_fernet() -> Fernet:
    key = settings.ENCRYPTION_SECRET_KEY.encode('utf-8')
    # If the key is not a valid 32-byte url-safe base64 string, derive one deterministically
    try:
        return Fernet(key)
    except Exception:
        # Fallback to base64 encoding/padding if standard raw string provided
        key_32 = base64.urlsafe_b64encode(key.ljust(32)[:32])
        return Fernet(key_32)


def encrypt_session_string(session_str: str) -> str:
    """Encrypt a Telethon/Pyrogram StringSession token at rest."""
    if not session_str:
        return ""
    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(session_str.encode('utf-8'))
    return encrypted_bytes.decode('utf-8')


def decrypt_session_string(encrypted_session: str) -> str:
    """Decrypt an encrypted StringSession token back to plain text."""
    if not encrypted_session:
        return ""
    fernet = _get_fernet()
    decrypted_bytes = fernet.decrypt(encrypted_session.encode('utf-8'))
    return decrypted_bytes.decode('utf-8')
