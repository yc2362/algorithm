
"""Run: python -m unittest -v test_main.py"""
import os
import unittest
from unittest.mock import patch

from main import MAX_SAFE_INTEGER, app, binary_search_first


class BinarySearchTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.key_patch = patch.dict(os.environ, {"API_KEY": "test-secret"})
        self.key_patch.start()

    def tearDown(self):
        self.key_patch.stop()

    def request(self, data, key="test-secret"):
        return self.client.post(
            "/search", json=data, headers={"X-API-Key": key}
        )

    def test_health_requires_no_key(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")

    def test_search_requires_key(self):
        self.assertEqual(self.request({"numbers": [1], "target": 1}, "bad").status_code, 401)
        response = self.client.post("/search", json={"numbers": [1], "target": 1})
        self.assertEqual(response.status_code, 401)

    def test_first_duplicate(self):
        response = self.request({"numbers": [1, 2, 2, 2, 5], "target": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["result"]["index"], 1)
        self.assertTrue(response.json["result"]["found"])
        self.assertEqual(response.json["metrics"]["comparisons"], len(response.json["steps"]))

    def test_absent_negative_and_single(self):
        self.assertFalse(self.request({"numbers": [-10, -4, 0, 3], "target": -3}).json["result"]["found"])
        self.assertEqual(self.request({"numbers": [-8], "target": -8}).json["result"]["index"], 0)
        self.assertFalse(self.request({"numbers": [9], "target": 3}).json["result"]["found"])

    def test_unsorted_rejected(self):
        self.assertEqual(self.request({"numbers": [2, 1], "target": 2}).status_code, 400)

    def test_invalid_shapes_and_values_rejected(self):
        cases = [
            {"numbers": [], "target": 1},
            {"numbers": [1] * 65, "target": 1},
            {"numbers": [1.5], "target": 1},
            {"numbers": [True], "target": 1},
            {"numbers": [1], "target": False},
            {"numbers": [1], "target": MAX_SAFE_INTEGER + 1},
            {"numbers": "1,2", "target": 1},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(self.request(case).status_code, 400)

    def test_trace_invariants_all_small_arrays(self):
        # Exhaustive combinations of small sorted arrays, including duplicates.
        from itertools import combinations_with_replacement

        for size in range(1, 8):
            for values in combinations_with_replacement(range(-2, 3), size):
                numbers = list(values)
                for target in range(-3, 4):
                    response = binary_search_first(numbers, target)
                    expected = numbers.index(target) if target in numbers else None
                    self.assertEqual(response["result"]["index"], expected)
                    self.assertLessEqual(len(response["steps"]), size.bit_length())
                    self.assertEqual(
                        [step["number"] for step in response["steps"]],
                        list(range(1, len(response["steps"]) + 1)),
                    )
                    for step in response["steps"]:
                        self.assertTrue(step["left"] <= step["mid_index"] <= step["right"])
                        self.assertEqual(numbers[step["mid_index"]], step["mid_value"])

    def test_required_json_content_type(self):
        response = self.client.post("/search", data="not json", headers={"X-API-Key": "test-secret"})
        self.assertEqual(response.status_code, 415)


if __name__ == "__main__":
    unittest.main()
