import tempfile
import unittest
from pathlib import Path

import marketplace_catalog_store as store


class MarketplaceCatalogStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = store.CATALOG_PATH
        store.CATALOG_PATH = Path(self.tempdir.name) / "catalog.json"

    def tearDown(self):
        store.CATALOG_PATH = self.original_path
        self.tempdir.cleanup()

    def test_saves_and_searches_options(self):
        saved = store.save_catalog_options("29CM", [{
            "marketplace_item_no": "2465716",
            "marketplace_option_no": "26320335",
            "marketplace_item_name": "여행용 어댑터",
            "marketplace_option_name": "화이트",
            "stock": "996",
            "sale_status": "판매중",
        }])
        self.assertEqual(saved[0]["marketplace_option_no"], "26320335")
        self.assertEqual(len(store.search_catalog_options("화이트")), 1)
        self.assertEqual(len(store.search_catalog_options("2465716")), 1)

    def test_updates_cached_option_after_action(self):
        store.save_catalog_options("29CM", [{
            "marketplace_item_no": "2465716",
            "marketplace_option_no": "26320335",
            "marketplace_item_name": "여행용 어댑터",
            "marketplace_option_name": "화이트",
            "stock": "996",
            "sale_status": "판매중",
        }])

        self.assertTrue(store.update_catalog_option(
            "29CM", "2465716", "26320335", stock="0", sale_status="품절",
        ))
        row = store.search_catalog_options("26320335")[0]
        self.assertEqual(row["stock"], "0")
        self.assertEqual(row["sale_status"], "품절")


if __name__ == "__main__":
    unittest.main()
