import unittest

from inventory_display_filter import INVENTORY_DISPLAY_CODES, filter_inventory_display_rows


class InventoryDisplayFilterTest(unittest.TestCase):
    def test_reference_contains_all_excel_item_codes(self) -> None:
        self.assertEqual(len(INVENTORY_DISPLAY_CODES), 172)

    def test_only_exact_case_insensitive_codes_are_kept(self) -> None:
        rows = [
            {"code": "ACONE-Sliconpad_BK", "name": "exact"},
            {"code": "acone-sliconpad_cl", "name": "case-insensitive exact"},
            {"code": "ACONE-Sliconpad", "name": "approximate"},
            {"code": "NOT-IN-REFERENCE", "name": "unmatched"},
        ]

        filtered = filter_inventory_display_rows(rows)

        self.assertEqual(
            [row["name"] for row in filtered],
            ["exact", "case-insensitive exact"],
        )


if __name__ == "__main__":
    unittest.main()
