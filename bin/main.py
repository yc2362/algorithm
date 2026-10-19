"""탐색 알고리즘 교육용 무상태 API.

클라이언트가 매 요청에 전체 입력 상태를 전송하면, 서버는 입력을 검증하고
연산의 모든 단계에 대한 독립적인 스냅샷을 생성한다.
"""
from __future__ import annotations

import os
import re
from collections import deque
from copy import deepcopy
from typing import Annotated, Literal, Union

from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator


MAX_ARRAY_SIZE = 40
MAX_GRAPH_NODES = 20
MAX_GRAPH_EDGES = 60
NODE_PATTERN = re.compile(r"^[A-Za-z0-9가-힣_]{1,12}$")


class ArrayState(BaseModel):
    """배열 원본 전체(서버에 남겨 두는 세션 상태는 없음)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["array"]
    values: list[StrictInt] = Field(min_length=1, max_length=MAX_ARRAY_SIZE)


class GraphState(BaseModel):
    """그래프의 정점·간선·방향성을 포함한 전체 입력 상태."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["graph"]
    nodes: list[str] = Field(min_length=1, max_length=MAX_GRAPH_NODES)
    edges: list[tuple[str, str]] = Field(default_factory=list, max_length=MAX_GRAPH_EDGES)
    directed: bool = False

    @model_validator(mode="after")
    def check_graph(self) -> "GraphState":
        if any(not NODE_PATTERN.fullmatch(node) for node in self.nodes):
            raise ValueError("정점 이름은 1~12자의 영문·한글·숫자·_만 사용할 수 있습니다.")
        if len(self.nodes) != len(set(self.nodes)):
            raise ValueError("정점 이름이 중복되었습니다.")
        node_set = set(self.nodes)
        unique_edges: set[tuple[str, str]] = set()
        for a, b in self.edges:
            if a not in node_set or b not in node_set:
                raise ValueError(f"간선 {a}-{b}의 양 끝점은 정점 목록에 존재해야 합니다.")
            if a == b:
                raise ValueError("자기 자신으로 향하는 간선은 이 실습에서 지원하지 않습니다.")
            key = (a, b) if self.directed else tuple(sorted((a, b)))
            if key in unique_edges:
                raise ValueError(f"중복 간선이 존재합니다: {a}-{b}")
            unique_edges.add(key)
        return self


class AlgorithmRequest(BaseModel):
    """알고리즘과 입력 상태 간의 논리적 결합까지 검증한다."""

    model_config = ConfigDict(extra="forbid")
    algorithm: Literal["linear", "binary", "bfs", "dfs"]
    state: Annotated[Union[ArrayState, GraphState], Field(discriminator="kind")]
    target: Union[StrictInt, str, None] = None
    start: str | None = None

    @model_validator(mode="after")
    def validate_algorithm_contract(self) -> "AlgorithmRequest":
        if self.algorithm in ("linear", "binary"):
            if not isinstance(self.state, ArrayState):
                raise ValueError("선형·이분 탐색은 배열 상태(kind=array)가 필요합니다.")
            if type(self.target) is not int:
                raise ValueError("배열 탐색의 목표값은 정수여야 합니다.")
            if self.start is not None:
                raise ValueError("배열 탐색에는 시작 정점을 지정하지 않습니다.")
            if self.algorithm == "binary":
                values = self.state.values
                if any(values[i] > values[i + 1] for i in range(len(values) - 1)):
                    raise ValueError("이분 탐색은 오름차순 정렬된 배열만 사용할 수 있습니다.")
        else:
            if not isinstance(self.state, GraphState):
                raise ValueError("BFS·DFS는 그래프 상태(kind=graph)가 필요합니다.")
            if self.start not in self.state.nodes:
                raise ValueError("시작 정점은 정점 목록에 존재해야 합니다.")
            if self.target is not None and (
                not isinstance(self.target, str) or self.target not in self.state.nodes
            ):
                raise ValueError("탐색 목표 정점은 정점 목록에 존재하거나 비워 두어야 합니다.")
        return self


ALGORITHM_NAMES = {
    "linear": "선형 탐색",
    "binary": "이분 탐색",
    "bfs": "너비 우선 탐색(BFS)",
    "dfs": "깊이 우선 탐색(DFS)",
}
COMPLEXITIES = {
    "linear": {"best": "O(1)", "worst": "O(n)", "space": "O(1)"},
    "binary": {"best": "O(1)", "worst": "O(log n)", "space": "O(1)"},
    "bfs": {"best": "O(1) (시작점에서 즉시 종료 시)", "worst": "O(V + E)", "space": "O(V)"},
    "dfs": {"best": "O(1) (시작점에서 즉시 종료 시)", "worst": "O(V + E)", "space": "O(V)"},
}


class TraceBuilder:
    """단계마다 원본과 참조가 분리된 스냅샷을 생성한다."""

    def __init__(self, algorithm: str, original_state: dict, target: int | str | None):
        self.algorithm = algorithm
        self.original_state = deepcopy(original_state)
        self.target = target
        self.steps: list[dict] = []
        self.live = deepcopy(original_state)
        self.stats = {"comparisons": 0, "visited_count": 0, "edges_examined": 0, "iterations": 0}

    def add(self, group: int, phase: str, title: str, detail: str) -> None:
        self.steps.append({
            "index": len(self.steps),
            "set_index": group,
            "phase": phase,
            "title": title,
            "detail": detail,
            "snapshot": deepcopy(self.live),
            "stats": deepcopy(self.stats),
        })

    def response(self, result: dict) -> dict:
        return {
            "ok": True,
            "algorithm": self.algorithm,
            "algorithm_name": ALGORITHM_NAMES[self.algorithm],
            "complexity": COMPLEXITIES[self.algorithm],
            "initial_state": deepcopy(self.original_state),
            "final_state": deepcopy(self.live),
            "result": result,
            "steps": self.steps,
            "total_steps": len(self.steps),
            "total_sets": len({step["set_index"] for step in self.steps}),
            "stats": deepcopy(self.stats),
        }


def run_array_algorithm(data: AlgorithmRequest) -> dict:
    assert isinstance(data.state, ArrayState)
    algorithm = data.algorithm
    values = list(data.state.values)
    target = data.target
    assert type(target) is int
    trace = TraceBuilder(algorithm, data.state.model_dump(), target)
    trace.live.update({
        "target": target,
        "low": None,
        "high": None,
        "mid": None,
        "current": None,
        "active": [],
        "examined": [],
        "found_index": None,
    })
    trace.add(0, "준비(init)", "탐색 시작", f"원소 {len(values)}개에서 목표값 {target}을(를) 찾습니다.")
    found_index: int | None = None

    if algorithm == "linear":
        for index, value in enumerate(values):
            group = index + 1
            trace.stats["iterations"] += 1
            trace.live.update({"current": index, "active": [index]})
            trace.add(group, "위치 이동(move)", f"인덱스 {index} 방문", "왼쪽에서 오른쪽으로 탐색 위치를 이동합니다.")
            trace.stats["comparisons"] += 1
            trace.add(group, "비교(compare)", f"{value}와 {target} 비교", f"values[{index}] == target → {value == target}")
            if value == target:
                found_index = index
                trace.live["found_index"] = index
                trace.add(group, "발견(found)", "목표값 발견", f"인덱스 {index}에서 목표값을 찾았습니다.")
                break
            trace.live["examined"].append(index)
            trace.add(group, "다음 위치(next)", "불일치 · 다음 원소", "현재 원소를 확인 완료로 표시합니다.")
    else:
        low, high = 0, len(values) - 1
        trace.live.update({"low": low, "high": high})
        while low <= high:
            group = trace.stats["iterations"] + 1
            trace.stats["iterations"] += 1
            trace.live.update({"low": low, "high": high, "mid": None, "current": None, "active": list(range(low, high + 1))})
            trace.add(group, "범위 확인(bounds)", f"탐색 범위 [{low}, {high}]", "남은 범위를 기준으로 중앙 인덱스를 계산합니다.")
            mid = (low + high) // 2
            value = values[mid]
            trace.live.update({"mid": mid, "current": mid, "active": [mid]})
            trace.add(group, "중앙 선택(mid)", f"중앙 인덱스 {mid}", f"mid = ({low} + {high}) // 2 = {mid}")
            trace.stats["comparisons"] += 1
            trace.add(group, "비교(compare)", f"{value}와 {target} 비교", "중앙값과 목표값의 대소를 판단합니다.")
            if value == target:
                found_index = mid
                trace.live["found_index"] = mid
                trace.add(group, "발견(found)", "목표값 발견", f"인덱스 {mid}에서 목표값을 찾았습니다.")
                break
            trace.live["examined"].append(mid)
            if value < target:
                low = mid + 1
                message = f"{value} < {target}이므로 왼쪽 구간을 제외합니다. low = {low}"
            else:
                high = mid - 1
                message = f"{value} > {target}이므로 오른쪽 구간을 제외합니다. high = {high}"
            trace.live.update({"low": low, "high": high, "active": [], "current": None, "mid": None})
            trace.add(group, "범위 축소(narrow)", "탐색 범위 축소", message)

    trace.live.update({"active": [], "current": found_index})
    trace.add(trace.stats["iterations"] + 1, "완료(done)",
              "탐색 완료", "목표값을 찾았습니다." if found_index is not None else "끝까지 탐색했지만 목표값이 없습니다.")
    return trace.response({
        "found": found_index is not None,
        "target": target,
        "index": found_index,
        "comparisons": trace.stats["comparisons"],
        "iterations": trace.stats["iterations"],
        "visited_count": trace.stats["iterations"],
    })


def graph_adjacency(state: GraphState) -> dict[str, list[str]]:
    """정점 입력 순서를 기준으로 인접 정점 탐색 순서를 고정한다."""
    adjacency = {name: [] for name in state.nodes}
    for a, b in state.edges:
        adjacency[a].append(b)
        if not state.directed:
            adjacency[b].append(a)
    position = {name: index for index, name in enumerate(state.nodes)}
    for neighbors in adjacency.values():
        neighbors.sort(key=position.__getitem__)
    return adjacency


def run_graph_algorithm(data: AlgorithmRequest) -> dict:
    assert isinstance(data.state, GraphState)
    start = data.start
    assert isinstance(start, str)
    target = data.target
    adjacency = graph_adjacency(data.state)
    trace = TraceBuilder(data.algorithm, data.state.model_dump(), target)
    frontier_type = "queue" if data.algorithm == "bfs" else "stack"
    trace.live.update({
        "start": start,
        "target": target,
        "frontier_type": frontier_type,
        "frontier": [start],
        "visited": [],
        "discovered": [start],
        "current": None,
        "active_edge": None,
        "comparison_node": None,
        "found_node": None,
        "path": [],
    })
    trace.add(0, "준비(init)", f"시작 정점 {start}", "초기 정점을 큐 또는 스택에 넣습니다.")
    order: list[str] = []
    found = False
    parent: dict[str, str | None] = {start: None}

    if data.algorithm == "bfs":
        queue: deque[str] = deque([start])
        discovered = {start}
        while queue:
            group = trace.stats["iterations"] + 1
            trace.stats["iterations"] += 1
            node = queue.popleft()
            trace.live.update({"frontier": list(queue), "current": node, "active_edge": None, "comparison_node": None})
            trace.add(group, "큐 꺼내기(dequeue)", f"{node} 꺼내기", "큐의 맨 앞 정점을 가져옵니다.")
            order.append(node)
            trace.stats["visited_count"] += 1
            trace.live["visited"] = list(order)
            trace.live["comparison_node"] = node if target is not None else None
            if target is not None:
                trace.stats["comparisons"] += 1
            trace.add(group, "방문(visit)", f"{node} 방문", "목표 정점과 비교합니다." if target is not None else "방문 순서에 기록합니다.")
            if node == target:
                found = True
                trace.live["found_node"] = node
                trace.add(group, "발견(found)", "목표 정점 발견", f"{node}에 도달했습니다.")
                break
            for neighbor in adjacency[node]:
                trace.stats["edges_examined"] += 1
                trace.live["active_edge"] = [node, neighbor]
                trace.live["comparison_node"] = neighbor
                trace.add(group, "인접 확인(edge)", f"{node} → {neighbor}", "인접 정점의 발견 여부를 검사합니다.")
                if neighbor not in discovered:
                    discovered.add(neighbor)
                    parent[neighbor] = node
                    queue.append(neighbor)
                    trace.live["discovered"].append(neighbor)
                    trace.live["frontier"] = list(queue)
                    trace.add(group, "큐 추가(enqueue)", f"{neighbor} 추가", "처음 발견한 정점을 큐의 뒤에 추가합니다.")
                else:
                    trace.add(group, "건너뛰기(skip)", f"{neighbor} 이미 발견", "중복 방문을 방지합니다.")
            trace.live.update({"active_edge": None, "comparison_node": None, "current": None})
            trace.add(group, "정점 완료(finish)", f"{node}의 인접 정점 확인 완료", "다음 큐 원소로 이동합니다.")
    else:
        # 재귀 DFS와 동일한 인접 순서의 반복형 DFS: 각 스택 프레임에 다음 간선 인덱스를 저장한다.
        stack: list[list[object]] = [[start, 0]]
        visited: set[str] = set()
        while stack:
            node = str(stack[-1][0])
            if node not in visited:
                group = trace.stats["iterations"] + 1
                trace.stats["iterations"] += 1
                visited.add(node)
                order.append(node)
                trace.stats["visited_count"] += 1
                trace.live.update({"visited": list(order), "current": node,
                                   "frontier": [str(frame[0]) for frame in stack],
                                   "comparison_node": node if target is not None else None,
                                   "active_edge": None})
                if target is not None:
                    trace.stats["comparisons"] += 1
                trace.add(group, "방문(visit)", f"{node} 방문", "스택 최상단 정점을 방문하고 목표를 확인합니다.")
                if node == target:
                    found = True
                    trace.live["found_node"] = node
                    trace.add(group, "발견(found)", "목표 정점 발견", f"{node}에 도달했습니다.")
                    break
            group = trace.stats["iterations"]
            next_index = int(stack[-1][1])
            if next_index < len(adjacency[node]):
                neighbor = adjacency[node][next_index]
                stack[-1][1] = next_index + 1
                trace.stats["edges_examined"] += 1
                trace.live.update({"current": node, "active_edge": [node, neighbor], "comparison_node": neighbor})
                trace.add(group, "인접 확인(edge)", f"{node} → {neighbor}", "아직 방문하지 않은 인접 정점인지 확인합니다.")
                if neighbor not in visited:
                    parent[neighbor] = node
                    stack.append([neighbor, 0])
                    trace.live["frontier"] = [str(frame[0]) for frame in stack]
                    if neighbor not in trace.live["discovered"]:
                        trace.live["discovered"].append(neighbor)
                    trace.add(group, "깊이 이동(push)", f"{neighbor} 스택 추가", "자식 정점으로 내려갑니다. 이후 이 정점을 방문합니다.")
                else:
                    trace.add(group, "건너뛰기(skip)", f"{neighbor} 방문 완료", "이미 방문한 정점이므로 이동하지 않습니다.")
            else:
                stack.pop()
                trace.live.update({"frontier": [str(frame[0]) for frame in stack],
                                   "current": str(stack[-1][0]) if stack else None,
                                   "active_edge": None, "comparison_node": None})
                trace.add(group, "되돌아가기(pop)", f"{node} 탐색 종료", "남은 간선이 없어 상위 정점으로 되돌아갑니다.")

    path: list[str] = []
    if found and isinstance(target, str):
        node_at: str | None = target
        while node_at is not None:
            path.append(node_at)
            node_at = parent[node_at]
        path.reverse()
    trace.live.update({"path": path, "active_edge": None, "comparison_node": None})
    trace.add(trace.stats["iterations"] + 1, "완료(done)", "탐색 완료",
              (f"목표 정점 {target}을(를) 찾았습니다." if found else
               "시작 정점에서 도달 가능한 모든 정점을 방문했습니다." if target is None else
               f"시작 정점에서 목표 {target}에 도달할 수 없습니다."))
    return trace.response({
        "found": found if target is not None else None,
        "target": target,
        "start": start,
        "order": order,
        "path": path,
        "visited_count": len(order),
        "comparisons": trace.stats["comparisons"],
        "edges_examined": trace.stats["edges_examined"],
        "iterations": trace.stats["iterations"],
    })


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 128 * 1024
# GAS의 UrlFetchApp 서버 간 통신에는 CORS가 필요하지 않다.
# 직접 브라우저에서 API를 호출할 경우를 위해 /api/*에 대해 별도로 허용한다.
cors_origins = os.environ.get("CORS_ORIGINS", "*")
CORS(app, resources={r"/api/*": {"origins": [part.strip() for part in cors_origins.split(",")],
                                  "methods": ["POST", "OPTIONS"]}})


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "midterm-algorithm-lab"})


@app.post("/api/execute")
def execute():
    if not request.is_json:
        return jsonify({"ok": False, "error": "Content-Type은 application/json이어야 합니다."}), 415
    try:
        payload = request.get_json()
        data = AlgorithmRequest.model_validate(payload)
        result = (run_array_algorithm(data) if data.algorithm in ("linear", "binary")
                  else run_graph_algorithm(data))
        return jsonify(result)
    except ValidationError as exc:
        details = [item["msg"].removeprefix("Value error, ") for item in exc.errors(include_url=False)]
        return jsonify({"ok": False, "error": "입력 데이터 검증 실패", "details": details}), 422
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"ok": False, "error": "요청 크기가 허용 범위를 초과했습니다."}), 413


@app.errorhandler(500)
def internal_error(_error):
    return jsonify({"ok": False, "error": "서버 내부 오류가 발생했습니다."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
