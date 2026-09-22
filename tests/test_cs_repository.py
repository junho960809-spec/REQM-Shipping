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
        )

        self.assertEqual(saved["version"], 2)
        self.assertEqual(draft_query.insert.call_args.args[0]["version"], 2)
        self.assertEqual(audit_query.insert.call_args.args[0]["action"], "draft_saved")


if __name__ == "__main__":
    unittest.main()
