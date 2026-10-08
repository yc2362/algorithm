
"""Binary-search teaching API for Google Cloud Run.

The API executes a leftmost binary search once and returns immutable search frames.
A Google Apps Script web application can replay the frames client-side.
"""

import hmac
import os
import time
from typing import Any

from flask import Flask, jsonify, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # Reject oversized JSON requests.
MAX_ITEMS = 64  # Keeps the interactive diagram manageable.
MAX_SAFE_INTEGER = (1 << 53) - 1  # JavaScript Number's exact integer range.


def validate_input(payload: Any) -> tuple[list[int], int]:
    """Enforce a safe, ascending integer array and an integer target."""
    if not isinstance(payload, dict):
        raise ValueError("JSON 객체로 요청해야 합니다.")

    numbers = payload.get("numbers")
    target = payload.get("target")
    if not isinstance(numbers, list):
        raise ValueError("numbers는 정수 배열이어야 합니다.")
    if not 1 <= len(numbers) <= MAX_ITEMS:
        raise ValueError(f"배열 원소는 1~{MAX_ITEMS}개여야 합니다.")
    if not isinstance(target, int) or isinstance(target, bool):
        raise ValueError("target은 정수여야 합니다.")
    if abs(target) > MAX_SAFE_INTEGER:
        raise ValueError("target이 JavaScript 안전 정수 범위를 초과합니다.")

    for index, value in enumerate(numbers):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"numbers[{index}]가 정수가 아닙니다.")
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError(f"numbers[{index}]가 안전 정수 범위를 초과합니다.")
        if index > 0 and numbers[index - 1] > value:
            raise ValueError("이진 검색은 오름차순으로 정렬된 배열만 지원합니다.")

    return numbers, target


def binary_search_first(numbers: list[int], target: int) -> dict[str, Any]:
    """Return the first matching index and a replayable comparison history.

    Invariant: after a match, keep searching the left portion for an earlier one.
    The binary-search state uses O(1) auxiliary space; captured frames use
    O(log n) additional space for visualization.
    """
    started = time.perf_counter()
    left, right = 0, len(numbers) - 1
    candidate = None
    steps = []

    while left <= right:
        middle = left + (right - left) // 2
        middle_value = numbers[middle]
        old_left, old_right = left, right

        if middle_value < target:
            relation = "less"
            left = middle + 1
            message = (
                f"{middle_value} < {target}: 목표값은 오른쪽 구간에 있으므로 "
                f"왼쪽 경계를 {left}(으)로 이동합니다."
            )
        elif middle_value > target:
            relation = "greater"
            right = middle - 1
            message = (
                f"{middle_value} > {target}: 목표값은 왼쪽 구간에 있으므로 "
                f"오른쪽 경계를 {right}(으)로 이동합니다."
            )
        else:
            relation = "equal"
            candidate = middle
            right = middle - 1
            message = (
                f"{middle_value} = {target}: 인덱스 {middle}를 후보로 기록하고 "
                "더 앞선 중복값이 있는지 왼쪽 구간을 검색합니다."
            )

        steps.append(
            {
                "number": len(steps) + 1,
                "left": old_left,
                "right": old_right,
                "mid_index": middle,
                "mid_value": middle_value,
                "relation": relation,
                "next_left": left,
                "next_right": right,
                "candidate_index": candidate,
                "message": message,
            }
        )

    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "algorithm": "binary_search_first",
        "input": {"numbers": numbers, "target": target},
        "result": {
            "found": candidate is not None,
            "index": candidate,
            "value": numbers[candidate] if candidate is not None else None,
        },
        "steps": steps,
        "metrics": {
            "n": len(numbers),
            "comparisons": len(steps),
            "worst_case_comparisons": len(numbers).bit_length(),
            "time_complexity": "O(log n)",
            "algorithm_auxiliary_space": "O(1)",
            "trace_storage": "O(log n)",
            "elapsed_ms": round(elapsed_ms, 4),
        },
    }


@app.get("/health")
def health():
    """Public liveness check without disclosing secrets."""
    return jsonify({"status": "ok", "service": "binary-search-api"})


@app.post("/search")
def search():
    """Authenticated binary-search execution."""
    expected_key = os.environ.get("API_KEY", "")
    provided_key = request.headers.get("X-API-Key", "")
    if not expected_key or not hmac.compare_digest(expected_key, provided_key):
        return jsonify({"error": "인증에 실패했습니다."}), 401

    if not request.is_json:
        return jsonify({"error": "Content-Type은 application/json이어야 합니다."}), 415

    try:
        numbers, target = validate_input(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(binary_search_first(numbers, target))


@app.errorhandler(413)
def oversized_request(_error):
    return jsonify({"error": "요청 데이터가 허용 크기를 초과했습니다."}), 413


if __name__ == "__main__":
    # For local development. Production uses Gunicorn (see Dockerfile).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

