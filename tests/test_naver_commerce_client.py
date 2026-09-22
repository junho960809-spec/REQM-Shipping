from __future__ import annotations

import unittest
from unittest.mock import Mock

from naver_commerce_client import NaverCommerceClient


class NaverCommerceClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = NaverCommerceClient("client-id", "$2b$12$abcdefghijklmnopqrstuu")
        self.client._request_json = Mock()

    def test_product_qna_uses_official_endpoint_and_unanswered_filter(self) -> None:
        self.client._request_json.return_value = {"contents": [{"questionId": 10}]}
        rows = self.client.product_qnas(answered=False, page=1, size=100)
        self.assertEqual(rows[0]["questionId"], 10)
        args, kwargs = self.client._request_json.call_args
        self.assertEqual(args[:2], ("GET", "/v1/contents/qnas"))
        self.assertFalse(kwargs["query"]["answered"])

    def test_customer_inquiry_uses_required_date_range(self) -> None:
        self.client._request_json.return_value = {"content": [{"inquiryNo": "1"}]}
        rows = self.client.customer_inquiries(start_date="2026-09-01", end_date="2026-09-22")
        self.assertEqual(rows[0]["inquiryNo"], "1")
        query = self.client._request_json.call_args.kwargs["query"]
        self.assertEqual(query["startSearchDate"], "2026-09-01")
        self.assertEqual(query["endSearchDate"], "2026-09-22")

    def test_product_qna_answer_uses_comment_content(self) -> None:
        self.client.answer_product_qna(42, "안내 답변")
        self.client._request_json.assert_called_once_with(
            "PUT", "/v1/contents/qnas/42", json_body={"commentContent": "안내 답변"}
        )


if __name__ == "__main__":
    unittest.main()
