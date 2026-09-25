from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from cs_repository import CsRepository, DraftConflictError


class CsRepositoryTests(unittest.TestCase):
    def test_upsert_cases_uses_shared_external_id_key(self) -> None:
        client = Mock()
        query = Mock()
        query.upsert.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": "case-1"}])
        client.table.return_value = query
        repository = CsRepository(client)

        count = repository.upsert_cases([{"channel": "product_qna", "external_id": "10"}])

        self.assertEqual(count, 1)
        query.upsert.assert_called_once_with(
            [{"channel": "product_qna", "external_id": "10"}],
            on_conflict="channel,external_id",
        )

    def test_save_rejects_stale_shared_draft_version(self) -> None:
        repository = CsRepository(Mock())
        repository.latest_draft = Mock(return_value={"version": 2})

        with self.assertRaises(DraftConflictError):
            repository.save_draft(
                case_id="case-1",
                operator_note="메모",
                generated_draft="초안",
                knowledge_refs=[],
                expected_version=1,
            )

    def test_save_creates_next_version_and_audit_log(self) -> None:
        client = Mock()
        draft_query = Mock()
        audit_query = Mock()
        draft_query.insert.return_value = draft_query
        draft_query.execute.return_value = SimpleNamespace(data=[{"id": "draft-2", "version": 2}])
        audit_query.insert.return_value = audit_query
        audit_query.execute.return_value = SimpleNamespace(data=[])
        client.table.side_effect = lambda name: draft_query if name == "cs_drafts" else audit_query
        repository = CsRepository(client)
        repository.latest_draft = Mock(return_value={"version": 1})

        saved = repository.save_draft(
            case_id="case-1",
            operator_note="사진 요청",
            generated_draft="사진을 보내주세요.",
            knowledge_refs=["새상품 교환"],
            expected_version=1,
            final_answer="사진과 구매일을 보내주세요.",
        )

        self.assertEqual(saved["version"], 2)
        self.assertEqual(draft_query.insert.call_args.args[0]["version"], 2)
        self.assertEqual(draft_query.insert.call_args.args[0]["generated_draft"], "사진을 보내주세요.")
        self.assertEqual(draft_query.insert.call_args.args[0]["final_answer"], "사진과 구매일을 보내주세요.")
        self.assertEqual(audit_query.insert.call_args.args[0]["action"], "draft_saved")

    def test_mark_sent_completes_case_and_writes_audit_log(self) -> None:
        client = Mock()
        queries = {name: Mock() for name in ("cs_drafts", "cs_cases", "cs_audit_logs")}
        for query in queries.values():
            query.update.return_value = query
            query.eq.return_value = query
            query.insert.return_value = query
            query.execute.return_value = SimpleNamespace(data=[])
        client.table.side_effect = lambda name: queries[name]
        repository = CsRepository(client)

        repository.mark_sent(case_id="case-1", draft_id="draft-1", external_id="42")

        queries["cs_drafts"].update.assert_called_once()
        queries["cs_cases"].update.assert_called_once_with({"status": "completed"})
        audit = queries["cs_audit_logs"].insert.call_args.args[0]
        self.assertEqual(audit["action"], "answer_sent")
        self.assertEqual(audit["details"]["external_id"], "42")

    def test_reuses_only_worker_edited_answer_for_same_model_and_policy(self) -> None:
        client = Mock()
        case_query = Mock()
        draft_query = Mock()
        case_query.select.return_value = case_query
        case_query.eq.return_value = case_query
        case_query.execute.return_value = SimpleNamespace(data=[{"id": "case-1"}])
        draft_query.select.return_value = draft_query
        draft_query.in_.return_value = draft_query
        draft_query.order.return_value = draft_query
        draft_query.limit.return_value = draft_query
        draft_query.execute.return_value = SimpleNamespace(data=[
            {
                "generated_draft": "자동 초안",
                "final_answer": "작업자가 고친 답변",
                "knowledge_refs": ["QPD330 최대 30W", "기기 권장 출력 확인"],
            },
            {
                "generated_draft": "수정 없는 답변",
                "final_answer": "수정 없는 답변",
                "knowledge_refs": ["QPD330 최대 30W"],
            },
        ])
        client.table.side_effect = lambda name: case_query if name == "cs_cases" else draft_query
        repository = CsRepository(client)

        result = repository.find_reusable_answer(
            product_model="QPD330",
            knowledge_refs=["QPD330 최대 30W", "기기 권장 출력 확인"],
        )

        self.assertEqual(result["final_answer"], "작업자가 고친 답변")
        case_query.eq.assert_called_once_with("product_model", "QPD330")

    def test_does_not_reuse_answer_from_different_inquiry_category(self) -> None:
        client = Mock()
        case_query = Mock()
        draft_query = Mock()
        case_query.select.return_value = case_query
        case_query.eq.return_value = case_query
        case_query.execute.return_value = SimpleNamespace(data=[{"id": "case-1"}])
        draft_query.select.return_value = draft_query
        draft_query.in_.return_value = draft_query
        draft_query.order.return_value = draft_query
        draft_query.limit.return_value = draft_query
        draft_query.execute.return_value = SimpleNamespace(data=[{
            "generated_draft": "자동 초안",
            "final_answer": "배송 답변",
            "knowledge_refs": ["category:주문_배송조회", "주문상태:배송 중", "실제 주문 상태 기준 배송 안내"],
        }])
        client.table.side_effect = lambda name: case_query if name == "cs_cases" else draft_query
        repository = CsRepository(client)

        result = repository.find_reusable_answer(
            product_model="QP1000C",
            knowledge_refs=["category:주문_취소", "주문상태:배송 중", "주문 상태에 따른 취소·반품 구분"],
        )

        self.assertIsNone(result)

    def test_does_not_reuse_order_answer_from_different_order_status(self) -> None:
        client = Mock()
        case_query = Mock()
        draft_query = Mock()
        case_query.select.return_value = case_query
        case_query.eq.return_value = case_query
        case_query.execute.return_value = SimpleNamespace(data=[{"id": "case-1"}])
        draft_query.select.return_value = draft_query
        draft_query.in_.return_value = draft_query
        draft_query.order.return_value = draft_query
        draft_query.limit.return_value = draft_query
        draft_query.execute.return_value = SimpleNamespace(data=[{
            "generated_draft": "자동 초안",
            "final_answer": "배송 중 답변",
            "knowledge_refs": ["category:주문_배송조회", "주문상태:배송 중", "실제 주문 상태 기준 배송 안내"],
        }])
        client.table.side_effect = lambda name: case_query if name == "cs_cases" else draft_query
        repository = CsRepository(client)

        result = repository.find_reusable_answer(
            product_model="QP1000C",
            knowledge_refs=["category:주문_배송조회", "주문상태:배송 완료", "실제 주문 상태 기준 배송 안내"],
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
