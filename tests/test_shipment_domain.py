from __future__ import annotations

import unittest

from shipment_domain import (
    ShipmentValidationError,
    positive_integer,
    shipment_idempotency_key,
    validate_prepared_shipment,
)


class ShipmentDomainTests(unittest.TestCase):
    def test_positive_integer_never_rounds_or_clamps(self) -> None:
        for value in (0, -3, 1.9, "", "NaN", True):
            with self.subTest(value=value), self.assertRaises(ShipmentValidationError):
                positive_integer(value)
        self.assertEqual(positive_integer("1,200"), 1200)

    def test_b2c_requires_shipping_fields_and_channel(self) -> None:
        with self.assertRaisesRegex(ShipmentValidationError, "판매처.*연락처.*주소"):
            validate_prepared_shipment(
                {"order_number": "O-1", "quantity": 1, "recipient": "홍길동", "zipcode": "01234",
                 "wekeep_product_name": "제품"},
                "b2c",
            )

    def test_idempotency_key_is_stable_and_sensitive_to_quantity(self) -> None:
        row = {"order_number": "O-1", "item_code": "A", "sku_no": "S", "quantity": 1,
               "recipient": "홍길동", "zipcode": "01234", "address": "서울"}
        first = shipment_idempotency_key([row], "b2c")
        second = shipment_idempotency_key([dict(row)], "b2c")
        changed = shipment_idempotency_key([{**row, "quantity": 2}], "b2c")
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
