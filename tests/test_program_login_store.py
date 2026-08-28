import tempfile
import unittest
from pathlib import Path

from program_login_store import delete_program_login, load_program_login, save_program_login


class ProgramLoginStoreTests(unittest.TestCase):
    def test_round_trip_uses_encrypted_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "program_login.json"
            save_program_login("worker@example.com", "secret-password", path)
            stored = path.read_text(encoding="utf-8")
            self.assertNotIn("worker@example.com", stored)
            self.assertNotIn("secret-password", stored)
            self.assertEqual(load_program_login(path), ("worker@example.com", "secret-password"))

    def test_delete_removes_saved_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "program_login.json"
            save_program_login("worker@example.com", "secret-password", path)
            delete_program_login(path)
            self.assertEqual(load_program_login(path), ("", ""))


if __name__ == "__main__":
    unittest.main()
