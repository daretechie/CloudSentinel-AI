import hashlib
import hmac
import base64
from cryptography.fernet import Fernet, MultiFernet
from typing import Optional, List

from app.core.config import get_settings

settings = get_settings()

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def _get_multi_fernet(primary_key: Optional[str], legacy_keys: Optional[List[str]] = None) -> MultiFernet:
    """
    Returns a MultiFernet instance for secret rotation.
    Supports both legacy SHA256 derivation and modern PBKDF2 (SEC-06).
    """
    all_keys = [primary_key] if primary_key else []
    if legacy_keys:
        all_keys.extend(legacy_keys)
    
    if not all_keys:
        # Fallback to a development key if nothing is configured
        all_keys = ["dev_fallback_key_do_not_use_in_prod"]

    fernet_instances = []
    settings = get_settings()
    salt = settings.KDF_SALT.encode()
    iterations = settings.KDF_ITERATIONS

    for k in all_keys:
        key_bytes = k.encode()
        
        # 1. Primary: Use PBKDF2HMAC (Secure KDF)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        derived_primary = kdf.derive(key_bytes)
        fernet_instances.append(Fernet(base64.urlsafe_b64encode(derived_primary)))
        
        # 2. Legacy: Use raw SHA256 digest (Old derivation)
        # We keep this as a secondary option so existing data can still be decrypted.
        # MultiFernet.encrypt always uses the FIRST instance (derived_primary).
        legacy_bytes = hashlib.sha256(key_bytes).digest()
        fernet_instances.append(Fernet(base64.urlsafe_b64encode(legacy_bytes)))
    
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
    except Exception as e:
        import structlog
        logger = structlog.get_logger()
        logger.error("decryption_failed", context=context, error=str(e))
        # Return None instead of "" to distinguish from an empty but valid field
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
    # SEC-06: Use separate key for blind indexing if available
    key_str = settings.BLIND_INDEX_KEY or settings.ENCRYPTION_KEY
    if not key_str:
        return None
        
    key = key_str.encode()
    
    # Normalize (lowercase) for consistent indexing of emails/names
    normalized_value = str(value).strip().lower()
    
    return hmac.new(key, normalized_value.encode(), hashlib.sha256).hexdigest()

def generate_new_key() -> str:
    """Generate a new Fernet key."""
    return Fernet.generate_key().decode()
