from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import wekeep_sku_store as store


class WeKeepSkuStoreTests(unittest.TestCase):
    def test_bundled_mapping_keeps_only_requested_acone_a_variants(self) -> None:
        rows = store.load_wekeep_sku_mappings(local_path=Path("__missing__"))
        by_code = {row["item_code"]: row for row in rows}

        self.assertEqual(len(rows), 173)
        self.assertEqual(by_code["QMC-ACONE-MB"]["sku_no"], "49322240816615")
        self.assertIn("/ A", by_code["QMC-ACONE-MB"]["product_name"])
        self.assertEqual(by_code["QMC-ACONE-SS"]["sku_no"], "76751484965672")
        self.assertIn("/ A", by_code["QMC-ACONE-SS"]["product_name"])

    def test_local_mapping_overrides_seed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed = root / "seed.json"
            local = root / "local.json"
            seed.write_text(json.dumps({"mappings": [{"item_code": "A", "sku_no": "1"}]}), encoding="utf-8")
            local.write_text(json.dumps({"mappings": [{"item_code": "a", "sku_no": "2"}]}), encoding="utf-8")

            rows = store.load_wekeep_sku_mappings(seed, local)

        self.assertEqual(rows, [{
            "item_code": "a", "wekeep_manage_code": "a", "product_name": "",
            "sku_no": "2", "customer_barcode": "", "is_active": True,
        }])

    def test_prepare_expands_components_and_multiplies_quantity(self) -> None:
        rows = store.prepare_wekeep_orders([{
            "status": "manual", "components": "A×2 + B×1", "quantity": "3",
            "order_number": "ORDER-1", "product_name": "세트상품", "channel": "와이즐리",
            "recipient": "홍길동", "phone": "010-1234-5678", "zipcode": "01234", "address": "서울",
        }], order_kind="b2c", mappings=[
            {"item_code": "A", "sku_no": "SKU-A", "is_active": True},
            {"item_code": "B", "sku_no": "SKU-B", "is_active": True},
        ], items=[
            {"item_code": "A", "standard_name": "에이"},
            {"item_code": "B", "standard_name": "비"},
        ])

        self.assertEqual([(row["sku_no"], row["quantity"]) for row in rows], [("SKU-A", 6), ("SKU-B", 3)])
        self.assertEqual([row["standard_product_name"] for row in rows], ["에이", "비"])
        self.assertTrue(all(row["state"] == "ready" for row in rows))

    def test_keeps_standard_and_wekeep_product_names_separate(self) -> None:
        rows = store.prepare_wekeep_orders([{
            "status": "exact", "components": "A×1", "quantity": "1",
            "product_name": "판매처의 긴 상품명", "matched_product": "표준 상품명",
        }], order_kind="b2c", mappings=[{
            "item_code": "A", "product_name": "위킵 공식 상품명", "sku_no": "SKU-A",
        }], items=[{"item_code": "A", "standard_name": "표준 상품명"}])

        self.assertEqual(rows[0]["converted_product_name"], "표준 상품명")
        self.assertEqual(rows[0]["standard_product_name"], "표준 상품명")
        self.assertEqual(rows[0]["wekeep_product_name"], "위킵 공식 상품명")

    def test_invalid_quantity_is_reviewed_without_rounding_or_clamping(self) -> None:
        base = {
            "status": "manual", "components": "A×1", "order_number": "ORDER-1",
            "product_name": "상품", "channel": "와이즐리", "recipient": "홍길동",
            "phone": "010-1234-5678", "zipcode": "01234", "address": "서울",
        }
        mapping = [{"item_code": "A", "sku_no": "SKU-A", "is_active": True}]
        for quantity in (0, -1, 1.5):
            with self.subTest(quantity=quantity):
                row = store.prepare_wekeep_orders(
                    [{**base, "quantity": quantity}], order_kind="b2c", mappings=mapping,
                )[0]
                self.assertEqual(row["state"], "review")
                self.assertIn("정수", row["reason"])

    def test_unmatched_order_stays_in_review(self) -> None:
        rows = store.prepare_wekeep_orders([{
            "status": "missing", "product_name": "타상품출고", "quantity": 1,
        }], order_kind="b2c", mappings=[])

        self.assertEqual(rows[0]["state"], "review")
        self.assertIn("먼저 확정", rows[0]["reason"])

    def test_inactive_mapping_is_not_used(self) -> None:
        rows = store.prepare_wekeep_orders([{
            "status": "exact", "components": "OLD×1", "quantity": 1,
        }], order_kind="b2b", mappings=[{"item_code": "OLD", "sku_no": "9", "is_active": False}])

        self.assertEqual(rows[0]["state"], "review")
        self.assertIn("SKU 미등록", rows[0]["reason"])


if __name__ == "__main__":
    unittest.main()
