import os
import logging
from dotenv import load_dotenv
load_dotenv()
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Fallback key for local dev if not provided (DO NOT USE IN PRODUCTION)
# In production, this must be set in the environment variables.
_DB_ENCRYPTION_KEY = os.environ.get("DB_ENCRYPTION_KEY")

_fernet = None
if _DB_ENCRYPTION_KEY:
    try:
        _fernet = Fernet(_DB_ENCRYPTION_KEY.encode('utf-8'))
    except Exception as e:
        logger.error(f"Failed to initialize Fernet with DB_ENCRYPTION_KEY: {e}")
else:
    logger.warning("DB_ENCRYPTION_KEY not set. Using a temporary key for this session (Data will be lost on restart!).")
    _fernet = Fernet(Fernet.generate_key())


def encrypt_text(text: str) -> str:
    """Encrypts a plain text string to a ciphertext string."""
    if text is None:
        return text
    if not isinstance(text, str):
        text = str(text)
    
    # If it's already encrypted (starts with 'gAAAAA'), don't double encrypt
    if text.startswith('gAAAAA'):
        return text
        
    try:
        return _fernet.encrypt(text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return text

def decrypt_text(ciphertext: str) -> str:
    """Decrypts a ciphertext string back to plain text."""
    if ciphertext is None:
        return ciphertext
    if not isinstance(ciphertext, str):
        return ciphertext
        
    # If it's not encrypted (doesn't start with Fernet header), return as is
    if not ciphertext.startswith('gAAAAA'):
        return ciphertext
        
    try:
        return _fernet.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        logger.error("Invalid token during decryption. The key might be wrong or the data corrupted.")
        return ciphertext # Return raw ciphertext or a fallback string depending on security needs
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return ciphertext
