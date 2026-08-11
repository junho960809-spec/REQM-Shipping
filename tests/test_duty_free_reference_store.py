from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from duty_free_reference_store import TEST_MAPPINGS, find_reference_mapping, load_reference_mappings
from ecount_client import collect_transfer_items
from matcher import ProductMatcher


class DutyFreeReferenceMappingTests(unittest.TestCase):
    def test_seeds_and_finds_five_lotte_reference_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reference_mappings.json"
            with patch("duty_free_reference_store.REFERENCE_MAPPING_PATH", path):
                rows = load_reference_mappings()
                self.assertEqual(rows, TEST_MAPPINGS)
                self.assertEqual(len(rows), 5)
                self.assertEqual(
                    find_reference_mapping("롯데면세점", "8809477248685")["item_code"],
                    "CASE-QP2000C_Hand_La",
                )

    def test_ref_mapping_is_included_in_warehouse_transfer(self) -> None:
        items = [{"item_code": row["item_code"], "standard_name": row["product_name"], "is_active": True} for row in TEST_MAPPINGS]
        matcher = ProductMatcher(items, [], [])
        orders = []
        for row in TEST_MAPPINGS:
            order = {
                "channel": row["channel"], "ref_no": row["ref_no"],
                "internal_item_code": row["item_code"], "product_name": row["product_name"],
                "quantity": "1",
            }
            order.update(matcher.match(order))
            orders.append(order)
        transfer_items, summary = collect_transfer_items(orders, "", items)
        self.assertEqual(summary, {"selected": 5, "included": 5, "excluded": 0})
        self.assertEqual(len(transfer_items), 5)

    def test_db_barcode_wins_before_name_matching(self) -> None:
        items = [{"item_code": "QP1000C1-Butter", "standard_name": "QP1000C 버터", "is_active": True}]
        barcodes = [{"barcode": "8809477248814", "item_code": "QP1000C1-Butter", "is_active": True}]
        matcher = ProductMatcher(items, [], [], barcodes=barcodes)
        result = matcher.match({"ref_no": "8809477248814", "product_name": "다른 이름"})
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["components"], "QP1000C1-Butter")
        self.assertIn("바코드", result["reason"])

    def test_unmatched_ref_falls_back_to_sku_item_code(self) -> None:
        items = [{"item_code": "SKU-100", "standard_name": "SKU 대체 품목", "is_active": True}]
        matcher = ProductMatcher(items, [], [], barcodes=[])

        result = matcher.match({
            "ref_no": "REF-NOT-IN-DB", "sku_no": "SKU-100", "product_name": "다른 이름",
        })

        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["components"], "SKU-100")
        self.assertIn("SKU 품목코드", result["reason"])

    def test_unmatched_ref_falls_back_to_sku_barcode(self) -> None:
        items = [{"item_code": "ITEM-200", "standard_name": "SKU 바코드 품목", "is_active": True}]
        barcodes = [{"barcode": "SKU-200", "item_code": "ITEM-200", "is_active": True}]
        matcher = ProductMatcher(items, [], [], barcodes=barcodes)

        result = matcher.match({
            "ref_no": "REF-NOT-IN-DB", "sku_no": "SKU-200", "product_name": "다른 이름",
        })

        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["components"], "ITEM-200")
        self.assertIn("SKU SKU-200 바코드", result["reason"])


if __name__ == "__main__":
    unittest.main()
