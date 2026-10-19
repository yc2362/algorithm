"""Stateless insertion sort API with validated, replayable snapshots."""
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, Field, ValidationError, ConfigDict, model_validator
from typing import Literal

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, methods=["POST", "OPTIONS"],
     allow_headers=["Content-Type"])

class SortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["sort"]
    values: list[int] = Field(min_length=1, max_length=30)
    order: Literal["asc", "desc"] = "asc"
    @model_validator(mode="after")
    def validate_values(self):
        if any(isinstance(v, bool) or not -999 <= v <= 999 for v in self.values):
            raise ValueError("Each value must be an integer between -999 and 999.")
        return self

def insertion_sort(values, order):
    """Generate deterministic trace; every step is a full independent snapshot."""
    a = values.copy()
    steps = []
    comparisons = shifts = 0
    def record(action, i=None, j=None, key=None, message=""):
        steps.append({"index": len(steps), "action": action, "values": a.copy(),
                      "sorted_prefix": 1 if i is None else i,
                      "active_index": j, "key": key, "message": message,
                      "comparisons": comparisons, "shifts": shifts})
    record("initial", message="Initial array")
    for i in range(1, len(a)):
        key = a[i]
        j = i - 1
        record("select", i, i, key, f"Select key {key} at index {i}")
        while j >= 0:
            comparisons += 1
            record("compare", i, j, key, f"Compare {a[j]} with key {key}")
            move = a[j] > key if order == "asc" else a[j] < key
            if not move:
                break
            a[j + 1] = a[j]
            shifts += 1
            record("shift", i, j + 1, key, f"Shift {a[j]} right")
            j -= 1
        a[j + 1] = key
        record("insert", i + 1, j + 1, key, f"Insert key {key} at index {j+1}")
    record("complete", len(a), message="Sorting complete")
    return {"result": a, "steps": steps, "metrics": {
        "comparisons": comparisons, "shifts": shifts, "step_count": len(steps)},
        "snapshot": {"values": a, "order": order},
        "complexity": {"best": "O(n)", "average": "O(n²)", "worst": "O(n²)",
                       "space": "O(1)", "stable": True}}

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "insertion-sort"})

@app.post("/api/insertion-sort")
def sort_api():
    try:
        if not request.is_json:
            return jsonify({"ok": False, "error": "Content-Type must be application/json"}), 415
        payload = SortRequest.model_validate(request.get_json())
        return jsonify({"ok": True, **insertion_sort(payload.values, payload.order)})
    except ValidationError as exc:
        return jsonify({"ok": False, "error": "Invalid input", "details": exc.errors(include_context=False)}), 422
    except Exception:
        app.logger.exception("Unexpected API error")
        return jsonify({"ok": False, "error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
