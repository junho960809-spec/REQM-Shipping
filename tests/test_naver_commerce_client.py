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
        self.assertIn("fromDate", kwargs["query"])
        self.assertIn("toDate", kwargs["query"])
        self.assertTrue(kwargs["query"]["fromDate"].endswith("+09:00"))
        self.assertTrue(kwargs["query"]["toDate"].endswith("+09:00"))

    def test_product_qna_accepts_explicit_search_period(self) -> None:
        self.client._request_json.return_value = {"contents": []}
        self.client.product_qnas(
            from_date="2026-09-01T00:00:00.000+09:00",
            to_date="2026-09-23T23:59:59.999+09:00",
        )
        query = self.client._request_json.call_args.kwargs["query"]
        self.assertEqual(query["fromDate"], "2026-09-01T00:00:00.000+09:00")
        self.assertEqual(query["toDate"], "2026-09-23T23:59:59.999+09:00")

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
