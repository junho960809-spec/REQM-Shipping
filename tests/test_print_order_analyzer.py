import unittest

from print_order_analyzer import analyze_text


class PrintOrderAnalyzerTests(unittest.TestCase):
    def test_different_recipient_labels_map_to_common_fields(self):
        for label in ("수령인", "받는사람", "수취인"):
            with self.subTest(label=label):
                result = analyze_text(
                    f"고려기프트\n{label}: 홍길동\n연락처: 010-1234-5678\n"
                    "배송주소: 서울 영등포구 양산로 43\n총수량: 300개\n출고요청일: 2026-09-01"
                )
                self.assertEqual(result.vendor, "고려기프트")
                self.assertEqual(result.fields["recipient"], "홍길동")
                self.assertIn("010-1234-5678", result.fields["contact"])
                self.assertEqual(result.fields["quantity"], "300개")

    def test_order_contact_is_not_used_as_shipping_recipient(self):
        result = analyze_text(
            "발주담당자: 이승현\n디자이너: 장혜진\n"
            "배송주소: 홍길동 서울 영등포구 양산로 43\n수취인 번호: 010-1234-5678"
        )
        self.assertEqual(result.fields["recipient"], "홍길동")
        self.assertNotIn(result.fields["recipient"], ("이승현", "장혜진"))

    def test_name_label_is_accepted_only_inside_delivery_group(self):
        result = analyze_text(
            "담당자 성명: 이승현\n연락처: 02-000-0000\n"
            "받는 곳: 서울 영등포구 양산로 43\n성명: 홍길동\n휴대폰: 010-1234-5678"
        )
        self.assertEqual(result.fields["recipient"], "홍길동")


if __name__ == "__main__":
    unittest.main()
