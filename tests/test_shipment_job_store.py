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


if __name__ == "__main__":
    unittest.main()
