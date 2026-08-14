import tempfile
import unittest
from pathlib import Path

from inventory_safety_store import load_safety_stocks, save_safety_stock


class InventorySafetyStoreTest(unittest.TestCase):
    def test_saves_and_loads_safety_stock_by_normalized_code(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "safety.json"
            save_safety_stock(" QMP5-WH ", 25, path)

            self.assertEqual(load_safety_stocks(path), {"qmp5-wh": 25.0})


if __name__ == "__main__":
    unittest.main()
