from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shipment_job_store import ShipmentJobStore


class ShipmentJobStoreTests(unittest.TestCase):
    @staticmethod
    def _rows() -> list[dict]:
        return [{"order_number": "O-1", "item_code": "A", "sku_no": "S", "quantity": 1,
                 "recipient": "홍길동", "zipcode": "01234", "address": "서울"}]

    def test_payload_is_encrypted_and_duplicate_active_job_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "jobs.sqlite3"
            store = ShipmentJobStore(path)
            job = store.create(self._rows(), "b2c")
            self.assertNotIn("홍길동", path.read_bytes().decode("utf-8", errors="ignore"))
            self.assertEqual(store.get(job["id"], include_payload=True)["payload"]["rows"], self._rows())
            with self.assertRaisesRegex(ValueError, "이미 존재"):
                store.create(self._rows(), "b2c")

    def test_state_transition_is_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = ShipmentJobStore(Path(folder) / "jobs.sqlite3")
            job = store.create(self._rows(), "b2c")
            store.transition(job["id"], "submitting", detail="전송 시작")
            completed = store.transition(job["id"], "completed", provider_reference="W-1")
            self.assertEqual(completed["state"], "completed")
            with self.assertRaisesRegex(ValueError, "허용되지 않는"):
                store.transition(job["id"], "submitting")

    def test_completed_job_retains_export_rows_and_tracking_progress(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = ShipmentJobStore(Path(folder) / "jobs.sqlite3")
            profile = {"id": "default_b2c", "name": "기본 택배출고"}
            job = store.create(
                self._rows(), "b2c", export_rows=self._rows(),
                output_profile=profile, source_name="A_출고.xlsx",
            )
            store.transition(job["id"], "submitting")
            store.transition(job["id"], "completed")
            tracking = [{**self._rows()[0], "tracking_match_state": "matched", "tracking_number": "1234567890"}]
            store.save_tracking_results(job["id"], tracking)
            recent = store.list_recent(include_payload=True)
            self.assertEqual(recent[0]["payload"]["source_name"], "A_출고.xlsx")
            self.assertEqual(recent[0]["payload"]["output_profile"], profile)
            self.assertEqual(recent[0]["matched_count"], 1)
            self.assertEqual(store.load_tracking_results(job["id"]), tracking)

    def test_tracking_progress_counts_orders_instead_of_set_component_rows(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = ShipmentJobStore(Path(folder) / "jobs.sqlite3")
            rows = [
                {**self._rows()[0], "item_code": "MAIN"},
                {**self._rows()[0], "item_code": "OPTION"},
            ]
            job = store.create(rows, "b2c")
            store.transition(job["id"], "submitting")
            store.transition(job["id"], "completed")
            store.save_tracking_results(job["id"], [
                {**row, "tracking_match_state": "matched", "tracking_number": "1234567890"}
                for row in rows
            ])
            recent = store.list_recent()
            self.assertEqual((recent[0]["matched_count"], recent[0]["tracking_total_count"]), (1, 1))

    def test_unknown_job_is_visible_for_confirmation_and_can_be_released_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = ShipmentJobStore(Path(folder) / "jobs.sqlite3")
            job = store.create(self._rows(), "b2c")
            store.transition(job["id"], "submitting")
            store.transition(job["id"], "verifying")
            store.transition(job["id"], "unknown")
            self.assertEqual(store.list_recent()[0]["state"], "unknown")
            store.transition(job["id"], "failed", detail="위킵 미등록 확인")
            replacement = store.create(self._rows(), "b2c")
            self.assertNotEqual(replacement["id"], job["id"])


if __name__ == "__main__":
    unittest.main()
