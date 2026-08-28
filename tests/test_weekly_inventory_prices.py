import unittest

from weekly_inventory_prices import active_items, price_map


class WeeklyInventoryPriceTests(unittest.TestCase):
    def test_vat_price_is_calculated_from_saved_base_cost(self):
        prices = price_map([{"item_code": " ABC ", "base_unit_cost": "100.123456"}])
        self.assertAlmostEqual(prices["abc"], 110.1358016)

    def test_only_active_settings_build_weekly_inventory_list(self):
        rows = [
            {"item_code": "A", "item_name": "사용", "is_active": True},
            {"item_code": "B", "item_name": "중지", "is_active": False},
        ]
        self.assertEqual(active_items(rows), [("A", "사용")])


if __name__ == "__main__":
    unittest.main()
