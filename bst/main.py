"""Google Cloud Run용 이진 검색 트리(BST) 단일 파일 서버.

이 파일에 BST 알고리즘과 Flask HTTP API를 모두 포함한다.
- GET  /health  : 서비스 상태 확인
- POST /api/bst : 초기화/검색/삽입/삭제/순회/키 범위 수행
- OPTIONS /api/bst : Flask-CORS가 브라우저 사전 요청을 처리

중요: Cloud Run의 요청은 서로 다른 인스턴스에서 처리될 수 있으므로
트리를 서버 전역 변수에 저장하지 않는다. 클라이언트가 매 요청에
이전 응답의 state를 전달하고, 서버는 그 상태를 복원해 연산한다.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge


# ────────────────────────────────────────────────────────────────────────────
# 1. 이진 검색 트리 자료구조·알고리즘
# ────────────────────────────────────────────────────────────────────────────
MAX_NODES = 63  # SVG 교육용 뷰의 가독성 및 응답 크기를 위한 한도
MIN_KEY = -999_999
MAX_KEY = 999_999


class ValidationError(ValueError):
    """사용자 입력 또는 직렬화된 트리의 형식이 잘못된 경우."""


@dataclass
class Node:
    """각 노드의 고유 ID는 키 변경(두 자식 삭제)과 별개로 유지된다."""
    key: int
    id: int
    left: Node | None = None
    right: Node | None = None


def validate_key(value: Any, *, field: str = "key") -> int:
    """bool은 파이썬에서 int 하위 클래스이므로 명시적으로 제외한다."""
    if type(value) is not int or not MIN_KEY <= value <= MAX_KEY:
        raise ValidationError(f"{field}: {MIN_KEY:,}~{MAX_KEY:,} 범위의 정수가 필요합니다.")
    return value


class binarySearchTree:
    """요청 단위의 이진 검색 트리 및 알고리즘별 실행 로그.

    공개 기능: __init__, init, search, add, remove, dump, min_key, max_key.
    루트 직렬화/역직렬화는 트리 구조와 노드 ID의 정합성을 검사한다.
    """

    def __init__(self, state: dict | None = None):
        self.root: Node | None = None
        self.next_id = 1
        self.steps: list[dict] = []
        self.visited_ids: set[int] = set()
        self.comparisons = 0
        if state is not None:
            self.root = self._deserialize(state)

    def _deserialize(self, data: dict) -> Node:
        """입력 트리의 순환 없는 JSON 구조, BST 순서와 ID 중복을 확인한다."""
        ids: set[int] = set()
        count = 0

        def read(item: Any, low: int | None, high: int | None, depth: int) -> Node | None:
            nonlocal count
            if item is None:
                return None
            if not isinstance(item, dict) or set(item) != {"id", "key", "left", "right"}:
                raise ValidationError("state: 각 노드는 id, key, left, right 필드가 필요합니다.")
            count += 1
            if count > MAX_NODES or depth > MAX_NODES:
                raise ValidationError(f"state: 노드 또는 깊이는 {MAX_NODES}를 초과할 수 없습니다.")
            key = validate_key(item["key"], field="state.key")
            node_id = item["id"]
            if type(node_id) is not int or node_id < 1 or node_id > 1_000_000 or node_id in ids:
                raise ValidationError("state: 노드 id가 잘못되었거나 중복되었습니다.")
            if (low is not None and key <= low) or (high is not None and key >= high):
                raise ValidationError("state: 이진 검색 트리의 키 정렬 조건에 위배됩니다.")
            ids.add(node_id)
            node = Node(key=key, id=node_id)
            node.left = read(item["left"], low, key, depth + 1)
            node.right = read(item["right"], key, high, depth + 1)
            return node

        result = read(data, None, None, 1)
        self.next_id = max(ids, default=0) + 1
        return result

    def _serialize(self, node: Node | None) -> dict | None:
        if node is None:
            return None
        return {
            "id": node.id,
            "key": node.key,
            "left": self._serialize(node.left),
            "right": self._serialize(node.right),
        }

    def state(self) -> dict | None:
        """클라이언트가 다음 요청에 그대로 보낼 수 있는 완전한 트리 상태."""
        return self._serialize(self.root)

    def _record(self, caption: str, focus: list[int] | None = None, *, kind: str = "visit") -> None:
        """불변 스냅샷을 즉시 생성해야 이전 단계로 돌아가도 내용이 일치한다."""
        self.steps.append({
            "caption": caption,
            "kind": kind,
            "focus_ids": focus or [],
            "visited_ids": sorted(self.visited_ids),
            "tree": self.state(),
        })

    def _visit(self, node: Node, caption: str) -> None:
        """비교한 노드의 수를 별도 수집하여 이론 복잡도와 실측을 구분한다."""
        self.comparisons += 1
        self.visited_ids.add(node.id)
        self._record(caption, [node.id])

    def _new_node(self, key: int) -> Node:
        node = Node(key=key, id=self.next_id)
        self.next_id += 1
        return node

    def _insert(self, key: int, *, animate: bool) -> tuple[bool, Node]:
        """반복문으로 부모/자식 위치를 추적한다. 중복 키는 삽입하지 않는다."""
        if self.root is None:
            self.root = self._new_node(key)
            if animate:
                self._record(f"{key}를 루트 노드로 삽입", [self.root.id], kind="change")
            return True, self.root

        cursor = self.root
        while True:
            self.comparisons += 1
            if animate:
                self.visited_ids.add(cursor.id)
                self._record(f"{key}와 노드 {cursor.key} 비교", [cursor.id])
            if key == cursor.key:
                if animate:
                    self._record(f"{key}가 이미 존재하므로 삽입하지 않음", [cursor.id], kind="result")
                return False, cursor
            side = "left" if key < cursor.key else "right"
            child = getattr(cursor, side)
            if child is None:
                child = self._new_node(key)
                setattr(cursor, side, child)
                if animate:
                    direction = "왼쪽" if side == "left" else "오른쪽"
                    self._record(f"{cursor.key}의 {direction} 자식에 {key} 삽입", [cursor.id, child.id], kind="change")
                return True, child
            cursor = child

    def init(self, keys: list[int]) -> dict:
        """기존 트리를 초기화한 다음, 입력 순서대로 삽입한다.

        초기화 화면은 삽입 '결과'만 단계별 기록한다. 전체 비교 경로를
        기록하면 편향 트리에서 O(n²)개의 대형 JSON 스냅샷이 발생하기 때문이다.
        """
        if not isinstance(keys, list) or len(keys) > MAX_NODES:
            raise ValidationError(f"keys: 최대 {MAX_NODES}개의 정수 리스트가 필요합니다.")
        for index, key in enumerate(keys):
            validate_key(key, field=f"keys[{index}]")
        self.root = None
        self.next_id = 1
        self.steps = []
        self.visited_ids = set()
        self.comparisons = 0
        self._record("빈 트리로 초기화", kind="start")
        inserted, duplicates = [], []
        for key in keys:
            created, node = self._insert(key, animate=False)
            if created:
                inserted.append(key)
                self._record(f"초기화: {key} 삽입 완료", [node.id], kind="change")
            else:
                duplicates.append(key)
                self._record(f"초기화: 중복 키 {key} 건너뜀", [node.id], kind="result")
        self._record(f"초기화 완료: {len(inserted)}개 노드", kind="result")
        return {"inserted": inserted, "duplicates": duplicates, "count": len(inserted)}

    def search(self, key: int) -> dict:
        """탐색 결과와 실제 비교 경로를 기록한다. 시간 O(h), 공간 O(1)."""
        key = validate_key(key)
        self._record(f"키 {key} 검색 시작", kind="start")
        cursor = self.root
        while cursor is not None:
            self._visit(cursor, f"검색: {key}와 {cursor.key} 비교")
            if key == cursor.key:
                self._record(f"검색 성공: {key} 발견", [cursor.id], kind="result")
                return {"found": True, "key": key}
            cursor = cursor.left if key < cursor.key else cursor.right
        self._record(f"검색 실패: 키 {key} 없음", kind="result")
        return {"found": False, "key": key}

    def add(self, key: int) -> dict:
        key = validate_key(key)
        if self.count() >= MAX_NODES:
            # 중복 키 삽입은 트리 크기를 늘리지 않으므로 허용한다.
            cursor = self.root
            exists = False
            while cursor is not None:
                if cursor.key == key:
                    exists = True
                    break
                cursor = cursor.left if key < cursor.key else cursor.right
            if not exists:
                raise ValidationError(f"트리가 가득 찼습니다. 최대 {MAX_NODES}개까지 삽입할 수 있습니다.")
        self._record(f"키 {key} 삽입 시작", kind="start")
        inserted, node = self._insert(key, animate=True)
        return {"inserted": inserted, "key": key, "node_id": node.id}

    def remove(self, key: int) -> dict:
        """삭제 3가지 분기: 리프 / 한 자식 / 두 자식(오른쪽 최소 후속자).

        후속자의 키를 대상 노드에 복사하고 후속자를 분리하는 두 변경은
        하나의 완결된 변경 스냅샷으로 캡처하여 중간의 BST 불변식 훼손을 노출하지 않는다.
        """
        key = validate_key(key)
        self._record(f"키 {key} 삭제 시작", kind="start")
        parent: Node | None = None
        cursor = self.root
        side = ""
        while cursor is not None:
            self._visit(cursor, f"삭제 대상 탐색: {key}와 {cursor.key} 비교")
            if key == cursor.key:
                break
            parent, side = cursor, ("left" if key < cursor.key else "right")
            cursor = getattr(cursor, side)
        if cursor is None:
            self._record(f"삭제할 키 {key}가 존재하지 않음", kind="result")
            return {"removed": False, "key": key, "case": "not_found"}

        if cursor.left is not None and cursor.right is not None:
            self._record(f"{key}: 자식 2개 → 오른쪽 서브트리에서 최소 키 검색", [cursor.id])
            successor_parent = cursor
            successor = cursor.right
            while successor.left is not None:
                self._visit(successor, f"후속자 탐색: {successor.key}에서 왼쪽으로 이동")
                successor_parent, successor = successor, successor.left
            self._visit(successor, f"중위 후속자 {successor.key} 발견")
            successor_key = successor.key
            # 오른쪽 서브트리의 최소 노드는 왼쪽 자식이 없고, 오른쪽 자식은 있을 수 있다.
            cursor.key = successor.key
            if successor_parent is cursor:
                successor_parent.right = successor.right
            else:
                successor_parent.left = successor.right
            self._record(
                f"대상 키 {key}를 {successor_key}로 교체하고 후속자 노드를 제거",
                [cursor.id], kind="change",
            )
            return {"removed": True, "key": key, "case": "two_children", "successor": successor_key}

        replacement = cursor.left if cursor.left is not None else cursor.right
        if parent is None:
            self.root = replacement
        else:
            setattr(parent, side, replacement)
        deletion_case = "one_child" if replacement is not None else "leaf"
        self._record(
            f"키 {key} 삭제: {'한쪽 자식을 연결' if replacement else '리프 노드를 제거'}",
            [replacement.id] if replacement else [], kind="change",
        )
        return {"removed": True, "key": key, "case": deletion_case}

    def dump(self) -> dict:
        """중위 순회를 단계별 기록하고, 전위·후위 결과도 함께 돌려준다."""
        self._record("트리 덤프 시작: 중위 순회 (왼쪽 → 자신 → 오른쪽)", kind="start")
        inorder: list[int] = []
        preorder: list[int] = []
        postorder: list[int] = []

        def traverse(node: Node | None) -> None:
            if node is None:
                return
            preorder.append(node.key)
            traverse(node.left)
            self._visit(node, f"중위 순회: {node.key} 방문 ({len(inorder) + 1}번째)")
            inorder.append(node.key)
            traverse(node.right)
            postorder.append(node.key)

        traverse(self.root)
        self._record(f"덤프 완료: 총 {len(inorder)}개", kind="result")
        return {"inorder": inorder, "preorder": preorder, "postorder": postorder}

    def min_key(self) -> int | None:
        """왼쪽 자식을 따라가며 최소 키를 찾는다. 빈 트리에서는 None."""
        cursor = self.root
        if cursor is None:
            self._record("빈 트리: 최솟값 없음", kind="result")
            return None
        while cursor is not None:
            self._visit(cursor, f"최솟값 탐색: {cursor.key} 확인")
            if cursor.left is None:
                self._record(f"최솟값: {cursor.key}", [cursor.id], kind="result")
                return cursor.key
            cursor = cursor.left
        return None

    def max_key(self) -> int | None:
        """오른쪽 자식을 따라가며 최대 키를 찾는다. 빈 트리에서는 None."""
        cursor = self.root
        if cursor is None:
            self._record("빈 트리: 최댓값 없음", kind="result")
            return None
        while cursor is not None:
            self._visit(cursor, f"최댓값 탐색: {cursor.key} 확인")
            if cursor.right is None:
                self._record(f"최댓값: {cursor.key}", [cursor.id], kind="result")
                return cursor.key
            cursor = cursor.right
        return None

    def key_range(self) -> dict:
        """키의 범위 버튼에 대응: 최솟값·최댓값 및 차이(최대-최소)."""
        self._record("최소·최대 키 탐색 시작", kind="start")
        minimum = self.min_key()
        maximum = self.max_key()
        self._record("키의 범위 탐색 완료", kind="result")
        return {"min_key": minimum, "max_key": maximum,
                "span": (maximum - minimum) if minimum is not None else None}

    def count(self) -> int:
        def walk(node: Node | None) -> int:
            return 0 if node is None else 1 + walk(node.left) + walk(node.right)
        return walk(self.root)

    def height(self) -> int:
        """노드 수 기준 높이: 빈 트리 0, 루트만 있을 때 1."""
        def walk(node: Node | None) -> int:
            return 0 if node is None else 1 + max(walk(node.left), walk(node.right))
        return walk(self.root)

    def metrics(self, action: str) -> dict:
        """측정치는 비교 횟수, Big-O는 이론적 상한/평균으로 명확히 구분."""
        complexity = {
            "init": ("O(n log n)", "O(n²)", "O(1)"),
            "search": ("O(log n)", "O(n)", "O(1)"),
            "add": ("O(log n)", "O(n)", "O(1)"),
            "remove": ("O(log n)", "O(n)", "O(1)"),
            "dump": ("O(n)", "O(n)", "O(h)"),
            "range": ("O(log n)", "O(n)", "O(1)"),
        }
        avg, worst, aux = complexity[action]
        return {
            "node_count": self.count(),
            "height_levels": self.height(),
            "comparisons_or_visits": self.comparisons,
            "step_count": len(self.steps),
            "time_average": avg,
            "time_worst": worst,
            "extra_space": aux,
            "height_note": "h=트리 높이. Big-O는 알고리즘 기준(단계별 스냅샷 저장 비용 제외)이며, 편향되면 h=n.",
        }


# ────────────────────────────────────────────────────────────────────────────
# 2. Flask 웹 서버 및 Cloud Run API
# ────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
# 매우 큰 요청을 거부하여 불필요한 서버 메모리 사용을 방지한다.
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

# 기본값 '*'는 교육용 공개 데모의 간편 설정이다. 실제 운영에서는
# CORS_ORIGINS='https://허용할-도메인'으로 제한한다.
# GAS의 UrlFetchApp 서버 간 통신에는 브라우저 CORS가 적용되지 않는다.
origin_setting = os.getenv("CORS_ORIGINS", "*").strip()
origins = "*" if origin_setting == "*" else [
    item.strip() for item in origin_setting.split(",") if item.strip()
]
CORS(app, resources={r"/api/*": {"origins": origins}},
     methods=["POST", "OPTIONS"],
     allow_headers=["Content-Type", "X-BST-Token"], max_age=3600)


@app.get("/health")
def health():
    """인증이 필요한 연산과 구별되는 단순 연결 확인 엔드포인트."""
    return jsonify({"ok": True, "service": "bst-cloud-run", "max_nodes": MAX_NODES})


@app.post("/api/bst")
def bst_api():
    """모든 연산은 요청의 state를 기준으로 독립 수행된다.

    초깃값은 action=init, keys=[...]로 전달한다.
    후속 연산은 action=add/remove/search/dump/range와 이전 응답의 state를 전달한다.
    성공 시: {ok, action, result, state, steps, metrics}.
    실패 시: HTTP 4xx/5xx와 {ok:false,error}.
    """
    started = time.perf_counter()

    # 공개 Cloud Run URL에서 API 오남용을 줄이기 위한 선택적 공유 토큰.
    # 실제 공개 서비스에는 IAM, 사용자 인증 및 요청 제한을 추가로 고려해야 한다.
    configured_token = os.getenv("BST_API_TOKEN", "")
    if configured_token and request.headers.get("X-BST-Token") != configured_token:
        return jsonify({"ok": False, "error": "API 접근 토큰이 유효하지 않습니다."}), 403

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "JSON 객체를 요청 본문으로 전송하세요."}), 400

    action = body.get("action")
    allowed = {"init", "search", "add", "remove", "dump", "range"}
    if not isinstance(action, str) or action not in allowed:
        return jsonify({"ok": False, "error": "지원하지 않는 연산입니다."}), 400

    try:
        if action == "init":
            tree = binarySearchTree()
            result = tree.init(body.get("keys", []))
        else:
            # state가 null이면 빈 트리 상태로 취급한다.
            tree = binarySearchTree(body.get("state"))
            if action in {"search", "add", "remove"}:
                key = validate_key(body.get("key"))
                result = getattr(tree, action)(key)
            elif action == "dump":
                result = tree.dump()
            else:
                result = tree.key_range()
    except ValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    metrics = tree.metrics(action)
    metrics["server_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return jsonify({
        "ok": True,
        "action": action,
        "result": result,
        "state": tree.state(),
        "steps": tree.steps,
        "metrics": metrics,
    })


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return jsonify({"ok": False, "error": "요청 본문 크기가 제한을 초과했습니다."}), 413


if __name__ == "__main__":
    # Cloud Run은 PORT 환경변수를 주입한다. 모든 네트워크 인터페이스에서 수신한다.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
