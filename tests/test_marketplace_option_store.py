from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import marketplace_option_store as store


class MarketplaceOptionStoreTests(unittest.TestCase):
    def test_mapping_is_upserted_by_marketplace_product_and_option(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mappings.json"
            with patch.object(store, "MAPPING_PATH", path):
                first = store.upsert_option_mapping({
                    "marketplace": "29CM", "marketplace_item_no": "2465716",
                    "marketplace_option_no": "26320335", "internal_option_name": "화이트",
                })
                second = store.upsert_option_mapping({
                    "marketplace": "29CM", "marketplace_item_no": "2465716",
                    "marketplace_option_no": "26320335", "internal_option_name": "화이트 리뉴얼",
                })
                self.assertEqual(len(first), 1)
                self.assertEqual(len(second), 1)
                self.assertEqual(second[0]["internal_option_name"], "화이트 리뉴얼")

    def test_action_is_recorded_as_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "actions.json"
            with patch.object(store, "ACTION_LOG_PATH", path):
                event = store.create_option_action({
                    "marketplace": "29CM", "marketplace_item_no": "2465716",
                    "marketplace_option_no": "26320335", "internal_item_code": "QTC-45W",
                }, "SOLD_OUT", "tester")
                self.assertEqual(event["status"], "PENDING")
                self.assertEqual(event["requested_by"], "tester")
                self.assertEqual(store.load_option_actions()[0]["action"], "SOLD_OUT")

                completed = store.complete_option_action(event["action_id"], "COMPLETED", "automation@reqm")
                self.assertEqual(completed["processed_by"], "automation@reqm")
                self.assertEqual(store.load_option_actions()[0]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
