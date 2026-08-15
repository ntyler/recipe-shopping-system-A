import base64

import pytest

from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor
from PushShoppingList.services.data_encryption_service import DataEncryptionError


def encoded_key(value=b"k" * 32):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def test_aes_gcm_round_trip_binds_ciphertext_to_record_identity():
    encryptor = AesGcmDataEncryptor(b"k" * 32, key_id="test-key-v1")

    envelope = encryptor.encrypt_json(
        {"totp_secret": "SECRET", "nested": [1, 2]},
        associated_data="account:account-1",
    )

    assert "SECRET" not in envelope
    assert encryptor.decrypt_json(
        envelope,
        associated_data="account:account-1",
    ) == {"nested": [1, 2], "totp_secret": "SECRET"}
    with pytest.raises(DataEncryptionError):
        encryptor.decrypt_json(envelope, associated_data="account:account-2")


def test_environment_encryptor_requires_key_and_rotation_identifier():
    with pytest.raises(DataEncryptionError, match="SHOPPING_APP_DATA_ENCRYPTION_KEY is required"):
        AesGcmDataEncryptor.from_environment({})

    with pytest.raises(DataEncryptionError, match="decode to exactly 32 bytes"):
        AesGcmDataEncryptor.from_environment({
            "SHOPPING_APP_DATA_ENCRYPTION_KEY": encoded_key(b"short"),
            "SHOPPING_APP_DATA_ENCRYPTION_KEY_ID": "v1",
        })

    with pytest.raises(DataEncryptionError, match="KEY_ID"):
        AesGcmDataEncryptor.from_environment({
            "SHOPPING_APP_DATA_ENCRYPTION_KEY": encoded_key(),
        })


def test_decrypt_rejects_wrong_key_identifier_and_ciphertext_tampering():
    original = AesGcmDataEncryptor(b"a" * 32, key_id="v1")
    envelope = original.encrypt_json({"password": "example"}, associated_data="store:1")

    wrong_id = AesGcmDataEncryptor(b"a" * 32, key_id="v2")
    with pytest.raises(DataEncryptionError, match="requires key id v1"):
        wrong_id.decrypt_json(envelope, associated_data="store:1")

    tampered = envelope.replace("ciphertext\":\"", "ciphertext\":\"A", 1)
    with pytest.raises(DataEncryptionError):
        original.decrypt_json(tampered, associated_data="store:1")
