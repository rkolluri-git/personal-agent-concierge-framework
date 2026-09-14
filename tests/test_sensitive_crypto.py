import tempfile
import unittest
from pathlib import Path

try:
    from sensitive_crypto import decrypt_age, decrypt_text, encrypt_age, encrypt_text, is_encrypted
except ModuleNotFoundError:
    decrypt_age = decrypt_text = encrypt_age = encrypt_text = is_encrypted = None


class SensitiveEncryptionTests(unittest.TestCase):
    @unittest.skipIf(encrypt_text is None, "cryptography is installed only in the Docker application")
    def test_age_and_contact_are_encrypted_and_can_be_decrypted(self):
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "family-secrets.key"
            encrypted_age = encrypt_age(15, key_path)
            encrypted_contact = encrypt_text("family@example.com", key_path)
            self.assertNotEqual(encrypted_age, "15")
            self.assertNotIn("family@example.com", encrypted_contact)
            self.assertTrue(is_encrypted(encrypted_age))
            self.assertTrue(is_encrypted(encrypted_contact))
            self.assertEqual(decrypt_age(encrypted_age, key_path), 15)
            self.assertEqual(decrypt_text(encrypted_contact, key_path), "family@example.com")
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
