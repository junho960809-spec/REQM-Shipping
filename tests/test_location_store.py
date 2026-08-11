from __future__ import annotations

import unittest

from location_store import local_to_remote, merge_remote_locations


class LocationStoreSyncTests(unittest.TestCase):
    def test_merges_active_remote_addresses_without_duplicates(self) -> None:
        local = [
            {
                "id": "local-lotte", "name": "롯데면세점 제2통물", "channel": "롯데면세점",
                "recipient": "", "phone": "", "zipcode": "", "address": "인천 주소 1", "message": "",
            }
        ]
        remote = [
            {
                "location_id": "DF1", "duty_free_name": "롯데면세점", "store_name": "제2통물",
                "phone": "032-000-0000", "address": "인천 주소 1", "is_active": True,
            },
            {
                "location_id": "DF2", "duty_free_name": "현대면세점", "store_name": "물류센터",
                "address": "인천 주소 2", "is_active": "true",
            },
            {
                "location_id": "DF3", "duty_free_name": "신라면세점", "store_name": "미등록",
                "address": "", "is_active": False,
            },
        ]

        merged, added = merge_remote_locations(local, remote)

        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["id"], "DF1")
        self.assertEqual(merged[0]["phone"], "032-000-0000")
        self.assertEqual(merged[1]["name"], "현대면세점 물류센터")

    def test_maps_local_location_back_to_database_schema(self) -> None:
        remote = local_to_remote(
            {
                "id": "DF4", "name": "현대면세점 인천공항 물류센터", "channel": "현대면세점",
                "recipient": "담당자", "phone": "02-000-0000", "zipcode": "12345",
                "address": "인천 주소", "message": "",
            }
        )

        self.assertEqual(remote["location_id"], "DF4")
        self.assertEqual(remote["store_name"], "인천공항 물류센터")
        self.assertTrue(remote["is_active"])


if __name__ == "__main__":
    unittest.main()
