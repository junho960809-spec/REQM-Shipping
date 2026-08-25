import unittest

from print_order_analyzer import analyze_text


class PrintOrderAnalyzerTests(unittest.TestCase):
    def test_different_recipient_labels_map_to_common_fields(self):
        for label in ("수령인", "성명", "받는사람"):
            with self.subTest(label=label):
                result = analyze_text(
                    f"고려기프트\n{label}: 홍길동\n연락처: 010-1234-5678\n"
                    "배송주소: 서울 영등포구 양산로 43\n총수량: 300개\n출고요청일: 2026-09-01"
                )
                self.assertEqual(result.vendor, "고려기프트")
                self.assertEqual(result.fields["recipient"], "홍길동")
                self.assertIn("010-1234-5678", result.fields["contact"])
                self.assertEqual(result.fields["quantity"], "300개")


if __name__ == "__main__":
    unittest.main()
