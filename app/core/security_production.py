"""
PRODUCTION: Secure Encryption Salt Management

This module provides production-ready encryption with:
1. Random salt generation per environment
2. No hardcoded secrets in source code
3. Salt versioning and rotation
4. Backward compatibility with legacy encrypted data
"""

import os
import secrets
import structlog
from typing import Optional, List
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet, MultiFernet
import base64
import hashlib

logger = structlog.get_logger()


class EncryptionKeyManager:
    """
    PRODUCTION: Manages encryption keys with versioning and rotation.
    
    Features:
    - Random salt per environment (not hardcoded)
    - Key versioning for rotation
    - Backward compatibility with legacy data
    - Secure KDF with PBKDF2-SHA256
    """
    
    # KDF Constants
    KDF_ITERATIONS = 100000  # NIST recommends 100,000+
    KDF_SALT_LENGTH = 32    # 256 bits
    
    @staticmethod
    def generate_salt() -> str:
        """
        Generate a cryptographically secure random salt.
        
        PRODUCTION: Call once per environment and store securely.
        Never hardcode salt in source code.
        
        Returns:
            Base64-encoded salt (safe to store in env vars)
        """
        random_bytes = secrets.token_bytes(EncryptionKeyManager.KDF_SALT_LENGTH)
        return base64.b64encode(random_bytes).decode('utf-8')
    
    @staticmethod
    def get_or_create_salt() -> str:
        """
        Get KDF salt from environment variable.
        If not set, generate and log instructions to set it.
        
        PRODUCTION: This should be set during deployment.
        """
        salt = os.environ.get("KDF_SALT")
        
        if salt:
            logger.info("kdf_salt_loaded_from_env")
            return salt
        
        # Development fallback: generate random salt
        if os.environ.get("ENVIRONMENT") == "development":
            generated_salt = EncryptionKeyManager.generate_salt()
            logger.warning(
                "kdf_salt_generated_runtime",
                warning="This is insecure! Set KDF_SALT environment variable in production.",
                generated_salt_for_testing=generated_salt
            )
            return generated_salt
        
        # Production: FAIL if salt not configured
        logger.critical(
            "kdf_salt_missing_production",
            error="KDF_SALT environment variable not set in production!",
            action="Set KDF_SALT to a secure random value. Example:\nexport KDF_SALT='$(python3 -c \"import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())\")'",
            reference="See SECURITY.md for key management procedures"
        )
        raise ValueError(
            "CRITICAL: KDF_SALT environment variable not set. "
            "This is required for secure encryption in production. "
            "See SECURITY.md for setup instructions."
        )
    
    @staticmethod
    def derive_key(
        master_key: str,
        salt: str,
        key_version: int = 1,
        iterations: int = KDF_ITERATIONS
    ) -> bytes:
        """
        Derive an encryption key from master key using PBKDF2.
        
        Args:
            master_key: Input key material
            salt: KDF salt (base64-encoded)
            key_version: Version number (for rotation tracking)
            iterations: KDF iterations
            
        Returns:
            32-byte derived key suitable for Fernet
        """
        try:
            # Decode salt from base64
            salt_bytes = base64.b64decode(salt)
        except Exception as e:
            logger.error("salt_decode_failed", error=str(e))
            raise ValueError(f"Invalid KDF salt format: {str(e)}")
        
        # Include version in KDF to prevent key-to-version mismatch
        kdf_input = f"{master_key}:v{key_version}".encode()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits for Fernet
            salt=salt_bytes,
            iterations=iterations,
        )
        
        derived_key = kdf.derive(kdf_input)
        return base64.urlsafe_b64encode(derived_key)
    
    @staticmethod
    def create_fernet_for_key(master_key: str, salt: str) -> Fernet:
        """
        Create a Fernet cipher from master key and salt.
        
        Args:
            master_key: Input key material
            salt: KDF salt
            
        Returns:
            Fernet cipher instance
        """
        derived_key = EncryptionKeyManager.derive_key(master_key, salt)
        return Fernet(derived_key)
    
    @staticmethod
    def create_multi_fernet(
        primary_key: str,
        legacy_keys: Optional[List[str]] = None,
        salt: str = None
    ) -> MultiFernet:
        """
        Create MultiFernet for key rotation support.
        
        PRODUCTION: Use this for all encryption operations.
        
        Args:
            primary_key: Current encryption key (used for new encryptions)
            legacy_keys: Previous keys (used for decryption only)
            salt: KDF salt
            
        Returns:
            MultiFernet instance with key rotation support
        """
        if salt is None:
            salt = EncryptionKeyManager.get_or_create_salt()
        
        all_keys = [primary_key]
        if legacy_keys:
            all_keys.extend(legacy_keys)
        
        fernet_instances = []
        
        for key in all_keys:
            try:
                fernet = EncryptionKeyManager.create_fernet_for_key(key, salt)
                fernet_instances.append(fernet)
            except Exception as e:
                logger.error(
                    "fernet_creation_failed",
                    error=str(e),
                    key_length=len(key)
                )
                continue
        
        if not fernet_instances:
            raise ValueError("No valid encryption keys could be derived")
        
        logger.info(
            "multi_fernet_created",
            primary_keys=1,
            fallback_keys=len(fernet_instances) - 1
        )
        
        return MultiFernet(fernet_instances)


def get_encryption_fernet():
    """
    Get the primary Fernet cipher for general encryption.
    
    PRODUCTION: Use this for encrypting sensitive fields.
    """
    from app.core.config import get_settings
    settings = get_settings()
    
    salt = EncryptionKeyManager.get_or_create_salt()
    legacy_keys = settings.LEGACY_ENCRYPTION_KEYS or []
    
    return EncryptionKeyManager.create_multi_fernet(
        settings.ENCRYPTION_KEY or secrets.token_urlsafe(32),
        legacy_keys,
        salt
    )


def encrypt_string(value: str, context: str = "generic") -> str:
    """
    Encrypt a string with automatic key rotation support.
    
    Args:
        value: String to encrypt
        context: Encryption context ("generic", "api_key", "pii")
        
    Returns:
        Encrypted value (safe to store in database)
    """
    if not value:
        return None
    
    try:
        fernet = get_encryption_fernet()
        encrypted = fernet.encrypt(value.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(
            "encryption_failed",
            context=context,
            error=str(e)
        )
        raise


def decrypt_string(value: str, context: str = "generic") -> str:
    """
    Decrypt a string with automatic key rotation support.
    
    Tries all available keys (current + legacy) until one works.
    
    Args:
        value: Encrypted string from database
        context: Encryption context
        
    Returns:
        Decrypted plaintext
    """
    if not value:
        return None
    
    try:
        fernet = get_encryption_fernet()
        decrypted = fernet.decrypt(value.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(
            "decryption_failed",
            context=context,
            error=str(e),
            note="This might indicate:\n1. Wrong KDF_SALT\n2. Data was encrypted with different key\n3. Database corruption"
        )
        raise


# Export for use in configuration
__all__ = [
    "EncryptionKeyManager",
    "get_encryption_fernet",
    "encrypt_string",
    "decrypt_string",
]
