from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from main import ItemManagerDialog
from wekeep_sku_store import load_wekeep_sku_mappings


class FakeQuery:
    def __init__(self, client, table: str):
        self.client = client
        self.table = table
        self.action = ""
        self.payload = None
        self.filters = []

    def update(self, payload): self.action, self.payload = "update", payload; return self
    def delete(self): self.action = "delete"; return self
    def insert(self, payload): self.action, self.payload = "insert", payload; return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def execute(self):
        self.client.operations.append((self.table, self.action, self.payload, tuple(self.filters)))
        return type("Response", (), {"data": []})()


class FakeClient:
    def __init__(self): self.operations = []
    def table(self, name): return FakeQuery(self, name)


class ItemShippingInfoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_edits_name_barcodes_and_wekeep_sku_from_one_screen(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sku_path = Path(folder) / "sku.json"
            client = FakeClient()
            items = [{"item_code": "ITEM-A", "standard_name": "이전 이름", "is_active": True}]
            barcodes = [{"item_code": "ITEM-A", "barcode": "8800000000001", "is_active": True}]
            dialog = ItemManagerDialog(client, items, barcodes, sku_path=sku_path)
            dialog.shipping_grid.selectRow(0)
            dialog.shipping_name.setText("새 상품명")
            dialog.shipping_barcodes.setText("8800000000002, 8800000000003")
            dialog.shipping_sku.setText("12345678901234")
            dialog.shipping_wekeep_name.setText("위킵 상품명")
            with patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning"), patch.object(QMessageBox, "critical") as critical:
                dialog.save_shipping_info()
            dialog.close()

            mapping = load_wekeep_sku_mappings(seed_path=Path("__missing__"), local_path=sku_path)

        self.assertFalse(critical.called)
        self.assertEqual(items[0]["standard_name"], "새 상품명")
        self.assertEqual({row["barcode"] for row in barcodes}, {"8800000000002", "8800000000003"})
        self.assertEqual(mapping[0]["sku_no"], "12345678901234")
        self.assertEqual(mapping[0]["product_name"], "위킵 상품명")
        self.assertTrue(any(operation[0] == "items" and operation[1] == "update" for operation in client.operations))
        self.assertTrue(any(operation[0] == "item_barcodes" and operation[1] == "delete" for operation in client.operations))
        self.assertTrue(any(operation[0] == "item_barcodes" and operation[1] == "insert" for operation in client.operations))


if __name__ == "__main__":
    unittest.main()
