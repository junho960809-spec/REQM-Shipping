from __future__ import annotations

import unittest

from product_knowledge import detect_model, get_product_knowledge


class ProductKnowledgeTests(unittest.TestCase):
    def test_sales_variant_alias_maps_to_canonical_model(self) -> None:
        self.assertEqual(detect_model("[리큐엠] 보조배터리 QP1000C1 네온그린"), "QP1000C")

    def test_renewed_qpd365_model_uses_n_suffix(self) -> None:
        self.assertEqual(detect_model("QPD365-N 고속 충전기"), "QPD365N")
        self.assertEqual(get_product_knowledge("QPD365N").model, "QPD365N")

    def test_discontinued_model_has_compensation_sale_replacement(self) -> None:
        old = get_product_knowledge("QP2000A")
        self.assertTrue(old.discontinued)
        self.assertEqual(old.replacement_model, "QP2000C")

    def test_confirmed_power_specs_are_kept_in_one_catalog(self) -> None:
        self.assertEqual(get_product_knowledge("QP1000C").capacity_wh, 37)
        self.assertEqual(get_product_knowledge("QP2000C").capacity_wh, 74)
        self.assertEqual(get_product_knowledge("QPD330").max_output_w, 30)
        self.assertEqual(get_product_knowledge("Q1500").max_output_w, 15)


if __name__ == "__main__":
    unittest.main()
