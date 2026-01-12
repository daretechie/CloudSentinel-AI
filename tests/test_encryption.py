import pytest
from app.models.llm import LLMBudget
from app.core.security import encrypt_string, decrypt_string, generate_new_key
from uuid import uuid4
from unittest.mock import patch

def test_encryption_decryption_utilities():
    """Verify that the encrypt and decrypt functions work correctly."""
    plain_text = "sk-1234567890abcdef"
    
    # Use a stable key for the test
    with patch('app.core.security.settings') as mock_settings:
        mock_settings.ENCRYPTION_KEY = generate_new_key()
        encrypted = encrypt_string(plain_text)
        assert encrypted != plain_text
        
        decrypted = decrypt_string(encrypted)
        assert decrypted == plain_text

def test_encryption_with_different_keys():
    """Verify that different keys result in different ciphertexts and fail decryption."""
    plain = "test-secret"
    k1 = generate_new_key()
    k2 = generate_new_key()
    
    # Encrypt with k1
    with patch('app.core.security.settings') as mock_settings:
        mock_settings.ENCRYPTION_KEY = k1
        enc1 = encrypt_string(plain)
        assert decrypt_string(enc1) == plain

    # Try to decrypt with k2
    with patch('app.core.security.settings') as mock_settings:
        mock_settings.ENCRYPTION_KEY = k2
        # Decrypt should fail because of different keys
        assert decrypt_string(enc1) == ""

@pytest.mark.asyncio
async def test_llm_budget_transparent_encryption():
    """Verify that the model property handles encryption transparently."""
    tenant_id = uuid4()
    budget = LLMBudget(tenant_id=tenant_id)
    
    test_key = "sk-ant-test-123"
    
    # Set the property
    budget.openai_api_key = test_key
    
    # Check that the underlying column is encrypted
    assert budget._openai_api_key != test_key
    assert "sk-ant" not in budget._openai_api_key
    
    # Check that the property returns the decrypted value
    assert budget.openai_api_key == test_key
    
    # Verify setter with None
    budget.openai_api_key = None
    assert budget._openai_api_key is None
    assert budget.openai_api_key == "" # decrypt_string returns "" for None

def test_generate_new_key():
    """Ensure generate_new_key produces a valid Fernet key."""
    key = generate_new_key()
    assert isinstance(key, str)
    assert len(key) == 44 # Fernet keys are base64 encoded 32 bytes
