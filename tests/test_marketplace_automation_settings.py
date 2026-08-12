import tempfile
import unittest
from pathlib import Path

import marketplace_automation_settings as settings


class MarketplaceAutomationSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_settings = settings.SETTINGS_PATH
        settings.SETTINGS_PATH = Path(self.tempdir.name) / "REQM" / "settings.json"

    def tearDown(self):
        settings.SETTINGS_PATH = self.original_settings
        self.tempdir.cleanup()

    def test_allows_new_dedicated_profile_folder(self):
        profile = settings.SETTINGS_PATH.parent / "29cm-automation-profile"
        settings.save_29cm_profile_path(str(profile))
        self.assertEqual(settings.load_29cm_profile_path(), str(profile))

    def test_rejects_missing_arbitrary_profile_folder(self):
        with self.assertRaises(ValueError):
            settings.save_29cm_profile_path(str(Path(self.tempdir.name) / "missing"))


if __name__ == "__main__":
    unittest.main()
