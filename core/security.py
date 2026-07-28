import base64
import logging
from cryptography.fernet import Fernet, InvalidToken
from config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    key = settings.ENCRYPTION_SECRET_KEY.encode('utf-8')
    try:
        return Fernet(key)
    except Exception:
        key_32 = base64.urlsafe_b64encode(key.ljust(32)[:32])
        return Fernet(key_32)


def encrypt_session_string(session_str: str) -> str:
    """Encrypt a Telethon StringSession token at rest."""
    if not session_str:
        return ""
    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(session_str.encode('utf-8'))
    return encrypted_bytes.decode('utf-8')


def decrypt_session_string(encrypted_session: str) -> str:
    """Decrypt an encrypted StringSession token. Returns empty string on any failure."""
    if not encrypted_session:
        return ""
    try:
        fernet = _get_fernet()
        decrypted_bytes = fernet.decrypt(encrypted_session.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except (InvalidToken, Exception) as e:
        logger.error(f"Session decryption failed — key mismatch or corrupted token: {e}")
        return ""

