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

    def test_device_contains_only_printing_machine(self):
        uv = analyze_text("UV인쇄 1곳\n인쇄문구: REQM\n수량: 50개")
        laser = analyze_text("레이저 각인\n문구: 감사합니다\n수량: 20개")
        self.assertEqual(uv.fields["device"], "UV")
        self.assertEqual(uv.fields["printing"], "REQM")
        self.assertEqual(laser.fields["device"], "레이저")
        self.assertEqual(laser.fields["printing"], "감사합니다")

    def test_no_printing_negates_sticker_option(self):
        result = analyze_text("스티커 옵션\n인쇄없음\n선물포장 무료\n수량: 50개")
        self.assertEqual(result.fields["printing"], "")
        self.assertEqual(result.fields["device"], "")
        self.assertEqual(result.fields["packaging"], "선물포장")

    def test_conflicting_quantities_are_held_for_review(self):
        result = analyze_text("품목코드 A530734\n511 2,000\n총수량 1,050개\n인쇄수량 1,000개")
        self.assertEqual(result.fields["item_code"], "A530734")
        self.assertEqual(result.fields["quantity"], "")
        self.assertTrue(any("수량 충돌" in issue for issue in result.issues))

    def test_address_number_is_not_mistaken_for_request_date(self):
        result = analyze_text(
            "발주일 2026년 09월 16일\n납기 09월 18일 금요일\n"
            "주소: 광주 광산구 송도로114번길 53 사서함 305-1\n수량: 50개"
        )
        self.assertEqual(result.fields["request_date"], "09-18")


if __name__ == "__main__":
    unittest.main()
