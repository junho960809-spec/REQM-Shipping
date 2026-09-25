from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher


class DraftConflictError(RuntimeError):
    pass


class CsRepository:
    def __init__(self, client) -> None:
        self.client = client

    def list_cases(self, status: str = "unanswered") -> list[dict]:
        if self.client is None:
            return []
        response = (
            self.client.table("cs_cases")
            .select("*")
            .eq("status", status)
            .order("updated_at", desc=True)
            .execute()
        )
        return list(response.data or [])

    def upsert_cases(self, cases: list[dict]) -> int:
        if self.client is None or not cases:
            return 0
        response = (
            self.client.table("cs_cases")
            .upsert(cases, on_conflict="channel,external_id")
            .execute()
        )
        return len(response.data or cases)

    def latest_draft(self, case_id: str) -> dict | None:
        if self.client is None or not case_id:
            return None
        response = (
            self.client.table("cs_drafts")
            .select("*")
            .eq("case_id", case_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
        return rows[0] if rows else None

    def save_draft(
        self,
        *,
        case_id: str,
        operator_note: str,
        generated_draft: str,
        knowledge_refs: list[str],
        expected_version: int,
        final_answer: str | None = None,
    ) -> dict:
        latest = self.latest_draft(case_id)
        server_version = int(latest.get("version") or 0) if latest else 0
        if server_version != expected_version:
            raise DraftConflictError("다른 작업자가 초안을 먼저 수정했습니다. 최신 내용을 다시 불러오세요.")
        payload = {
            "case_id": case_id,
            "operator_note": operator_note.strip(),
            "generated_draft": generated_draft.strip(),
            "final_answer": (final_answer if final_answer is not None else generated_draft).strip(),
            "knowledge_refs": knowledge_refs,
            "version": server_version + 1,
            "status": "draft",
        }
        response = self.client.table("cs_drafts").insert(payload).execute()
        rows = list(response.data or [])
        if not rows:
            raise RuntimeError("공용 초안을 저장하지 못했습니다.")
        saved = rows[0]
        self.client.table("cs_audit_logs").insert({
            "case_id": case_id,
            "draft_id": saved.get("id"),
            "action": "draft_saved",
            "details": {"version": saved.get("version")},
        }).execute()
        return saved

    @staticmethod
    def _question_similarity(left: str, right: str) -> float:
        def normalize(value: str) -> str:
            return " ".join(re.findall(r"[0-9A-Za-z가-힣]+", value.lower()))

        normalized_left = normalize(left)
        normalized_right = normalize(right)
        if not normalized_left or not normalized_right:
            return 0.0
        sequence_score = SequenceMatcher(None, normalized_left, normalized_right).ratio()
        left_tokens = set(normalized_left.split())
        right_tokens = set(normalized_right.split())
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        return max(sequence_score, token_score)

    def find_reusable_answer(
        self, *, product_model: str, knowledge_refs: list[str], question: str = ""
    ) -> dict | None:
        """Find a worker-edited answer for a similar question with matching policy context."""
        if self.client is None or not product_model.strip() or not knowledge_refs:
            return None
        case_response = (
            self.client.table("cs_cases")
            .select("id,question")
            .eq("product_model", product_model.strip().upper())
            .execute()
        )
        case_ids = [str(row.get("id") or "") for row in (case_response.data or []) if row.get("id")]
        case_questions = {
            str(row.get("id")): str(row.get("question") or "")
            for row in (case_response.data or [])
            if row.get("id")
        }
        if not case_ids:
            return None
        draft_response = (
            self.client.table("cs_drafts")
            .select("id,case_id,generated_draft,final_answer,knowledge_refs,status,updated_at")
            .in_("case_id", case_ids)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
        )
        requested = {str(value).strip() for value in knowledge_refs if str(value).strip()}
        requested_categories = {value for value in requested if value.startswith("category:")}
        requested_statuses = {value for value in requested if value.startswith("주문상태:")}
        best: tuple[float, dict] | None = None
        for row in draft_response.data or []:
            generated = str(row.get("generated_draft") or "").strip()
            final = str(row.get("final_answer") or "").strip()
            if not final or final == generated:
                continue
            refs = {str(value).strip() for value in (row.get("knowledge_refs") or []) if str(value).strip()}
            if requested_categories and not requested_categories.issubset(refs):
                continue
            row_statuses = {value for value in refs if value.startswith("주문상태:")}
            if requested_statuses and row_statuses != requested_statuses:
                continue
            comparable_requested = requested - requested_statuses
            comparable_refs = refs - row_statuses
            overlap = len(comparable_requested & comparable_refs)
            union = len(comparable_requested | comparable_refs)
            policy_score = overlap / union if union else 0.0
            minimum_overlap = 2 if len(comparable_requested) > 1 else 1
            if overlap < minimum_overlap or policy_score < 0.6:
                continue
            source_question = case_questions.get(str(row.get("case_id") or ""), "")
            question_score = self._question_similarity(question, source_question) if question.strip() else 0.0
            if question.strip() and question_score < 0.3:
                continue
            score = policy_score if not question.strip() else (policy_score * 0.65) + (question_score * 0.35)
            if best is None or score > best[0]:
                candidate = dict(row)
                candidate["_reuse_score"] = score
                candidate["_question_similarity"] = question_score
                candidate["_source_question"] = source_question
                best = (score, candidate)
        return best[1] if best else None

    def mark_sent(self, *, case_id: str, draft_id: str, external_id: str) -> None:
        if self.client is None:
            raise RuntimeError("CS 공용 저장소에 연결되어 있지 않습니다.")
        self.client.table("cs_drafts").update({
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", draft_id).execute()
        self.client.table("cs_cases").update({"status": "completed"}).eq("id", case_id).execute()
        self.client.table("cs_audit_logs").insert({
            "case_id": case_id,
            "draft_id": draft_id,
            "action": "answer_sent",
            "details": {"external_id": external_id},
        }).execute()
