import hashlib
import hmac
import base64
from cryptography.fernet import Fernet, MultiFernet
from typing import Optional, List

from app.core.config import get_settings

settings = get_settings()

def _get_multi_fernet(primary_key: Optional[str], legacy_keys: Optional[List[str]] = None) -> MultiFernet:
    """
    Returns a MultiFernet instance for secret rotation.
    Encodes/derives keys as needed.
    """
    all_keys = [primary_key] if primary_key else []
    if legacy_keys:
        all_keys.extend(legacy_keys)
    
    if not all_keys:
        # Fallback to a development key if nothing is configured
        all_keys = ["dev_fallback_key_do_not_use_in_prod"]

    fernet_instances = []
    for k in all_keys:
        # Derive 32-byte key from arbitrary string
        key_bytes = hashlib.sha256(k.encode()).digest()
        fernet_instances.append(Fernet(base64.urlsafe_b64encode(key_bytes)))
    
    return MultiFernet(fernet_instances)

def _get_api_key_fernet() -> MultiFernet:
    settings = get_settings()
    return _get_multi_fernet(
        settings.API_KEY_ENCRYPTION_KEY or settings.ENCRYPTION_KEY,
        settings.LEGACY_ENCRYPTION_KEYS
    )

def _get_pii_fernet() -> MultiFernet:
    settings = get_settings()
    return _get_multi_fernet(
        settings.PII_ENCRYPTION_KEY or settings.ENCRYPTION_KEY,
        settings.LEGACY_ENCRYPTION_KEYS
    )

def encrypt_string(value: str, context: str = "generic") -> str:
    """Symmetrically encrypt a string with rotation support."""
    if not value:
        return None
    
    if context == "api_key":
        f = _get_api_key_fernet()
    elif context == "pii":
        f = _get_pii_fernet()
    else:
        settings = get_settings()
        f = _get_multi_fernet(settings.ENCRYPTION_KEY, settings.LEGACY_ENCRYPTION_KEYS)
        
    return f.encrypt(value.encode()).decode()

def decrypt_string(value: str, context: str = "generic") -> str:
    """Symmetrically decrypt a string with rotation support."""
    if not value:
        return None
        
    try:
        if context == "api_key":
            f = _get_api_key_fernet()
        elif context == "pii":
            f = _get_pii_fernet()
        else:
            settings = get_settings()
            f = _get_multi_fernet(settings.ENCRYPTION_KEY, settings.LEGACY_ENCRYPTION_KEYS)
            
        return f.decrypt(value.encode()).decode()
    except Exception:
        # If decryption fails with all keys, return None
        return None


def generate_blind_index(value: str) -> str:
    """
    Generates a deterministic hash for searchable encryption.
    Uses HMAC-SHA256 with the application's ENCRYPTION_KEY.
    
    This allows us to perform exact-match lookups on encrypted data
    without being able to decrypt the hash back to the original value.
    """
    if not value or value == "":
        return None
    
    settings = get_settings()
    key = settings.ENCRYPTION_KEY.encode()
    
    # Normalize (lowercase) for consistent indexing of emails/names
    normalized_value = str(value).strip().lower()
    
    return hmac.new(key, normalized_value.encode(), hashlib.sha256).hexdigest()

def generate_new_key() -> str:
    """Generate a new Fernet key."""
    return Fernet.generate_key().decode()
