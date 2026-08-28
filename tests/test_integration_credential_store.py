import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integration_credential_store import (
    FIELDS,
    delete_integration_credentials,
    load_integration_credentials,
    save_integration_credentials,
)


class IntegrationCredentialStoreTests(unittest.TestCase):
    def test_round_trip_encrypts_every_saved_value(self):
        values = {field: f"secret-{field}" for field in FIELDS}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "credentials.json"
            with patch("integration_credential_store.protect_secret", side_effect=lambda value: value[::-1]), patch(
                "integration_credential_store.unprotect_secret", side_effect=lambda value: value[::-1]
            ):
                save_integration_credentials(values, path)
                raw = path.read_text(encoding="utf-8")
                self.assertNotIn("secret-ecount_password", raw)
                self.assertEqual(load_integration_credentials(path), values)

    def test_delete_removes_store(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "credentials.json"
            path.write_text("{}", encoding="utf-8")
            delete_integration_credentials(path)
            self.assertFalse(path.exists())

    def test_required_fields_are_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                save_integration_credentials({}, Path(folder) / "credentials.json")


if __name__ == "__main__":
    unittest.main()
