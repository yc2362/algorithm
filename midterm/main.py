"""Fixed-size (20) circular queue: stateless Cloud Run API.

Every request includes the complete queue snapshot. Each response includes
both the operation result and a sequence of visualizable snapshots.
"""
import os
from typing import Literal

from flask import Flask, jsonify, request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CAPACITY = 20
MAX_SAFE_INTEGER = 9007199254740991  # JavaScript Number.MAX_SAFE_INTEGER
Operation = Literal[
    'init', 'push', 'bulk_push', 'pop', 'size', 'status', 'peek',
    'clear', 'find', 'count', 'contains', 'dump'
]
app = Flask(__name__)


class QueueState(BaseModel):
    """Validate not only field types but the circular buffer's invariants."""
    model_config = ConfigDict(extra='forbid', strict=True)
    capacity: Literal[20]
    buffer: list[int | None]
    front: int
    rear: int
    size: int = Field(ge=0, le=CAPACITY)

    @model_validator(mode='after')
    def verify_invariants(self):
        if len(self.buffer) != CAPACITY:
            raise ValueError('buffer 길이는 정확히 20이어야 합니다.')
        if any(v is not None and abs(v) > MAX_SAFE_INTEGER for v in self.buffer):
            raise ValueError('JavaScript 안전 정수 범위를 초과했습니다.')
        if self.size == 0:
            if self.front != -1 or self.rear != -1 or any(v is not None for v in self.buffer):
                raise ValueError('빈 큐의 front/rear는 -1이며 모든 슬롯이 비어야 합니다.')
        else:
            if not 0 <= self.front < CAPACITY or not 0 <= self.rear < CAPACITY:
                raise ValueError('front/rear 인덱스 범위가 잘못되었습니다.')
            if self.rear != (self.front + self.size - 1) % CAPACITY:
                raise ValueError('front, rear, size 간 관계가 올바르지 않습니다.')
            used = {(self.front + i) % CAPACITY for i in range(self.size)}
            for i, value in enumerate(self.buffer):
                if (i in used) != (value is not None):
                    raise ValueError('사용 슬롯과 buffer 데이터의 배치가 일치하지 않습니다.')
        return self


class QueueRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    operation: Operation
    state: QueueState | None = None
    value: int | None = Field(default=None, ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)
    values: list[int] | None = Field(default=None, max_length=CAPACITY)


def empty_queue():
    return {'capacity': CAPACITY, 'buffer': [None] * CAPACITY,
            'front': -1, 'rear': -1, 'size': 0}


def ordered_positions(state):
    return [(state['front'] + i) % CAPACITY for i in range(state['size'])]


def push_one(state, value):
    """Mutate only this request's copied state, never a global variable."""
    if state['size'] >= CAPACITY:
        raise QueueError('QUEUE_FULL', '큐가 가득 차 push할 수 없습니다.')
    slot = 0 if state['size'] == 0 else (state['rear'] + 1) % CAPACITY
    if state['size'] == 0:
        state['front'] = slot
    state['buffer'][slot] = value
    state['rear'] = slot
    state['size'] += 1
    return slot


class QueueError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


COMPLEXITIES = {
    'init': ('O(20)', 'O(20)'), 'push': ('O(1)', 'O(1)'),
    'bulk_push': ('O(k)', 'O(k) 단계 기록'), 'pop': ('O(1)', 'O(1)'),
    'size': ('O(1)', 'O(1)'), 'status': ('O(1)', 'O(1)'),
    'peek': ('O(1)', 'O(1)'), 'clear': ('O(20)', 'O(1)'),
    'find': ('O(n)', 'O(n) 단계 기록'),
    'count': ('O(n)', 'O(n) 단계 기록'),
    'contains': ('O(n)', 'O(n) 단계 기록'),
    'dump': ('O(n)', 'O(n) 출력 및 단계 기록'),
}


def execute(payload):
    """Return snapshots for all observable steps; no persistent server state."""
    op = payload.operation
    state = empty_queue() if payload.state is None or op == 'init' else payload.state.model_dump()
    steps = []

    def step(title, description, active=None):
        steps.append({'number': len(steps) + 1, 'title': title,
                      'description': description, 'active': active or [],
                      'state': {'capacity': CAPACITY, 'buffer': state['buffer'][:],
                                'front': state['front'], 'rear': state['rear'],
                                'size': state['size']}})

    if op != 'init' and payload.state is None:
        raise QueueError('STATE_REQUIRED', '먼저 초기화를 실행해야 합니다.')
    if op in ('push', 'find', 'count', 'contains') and payload.value is None:
        raise QueueError('VALUE_REQUIRED', '정수 값을 입력해야 합니다.')
    if op == 'bulk_push' and not payload.values:
        raise QueueError('VALUES_REQUIRED', '삽입할 정수 배열을 입력해야 합니다.')

    step('요청 접수', f'{op} 연산 시작: 서버가 전달된 상태를 검증하고 복원했습니다.')
    result = {}

    if op == 'init':
        step('초기화 완료', '20개 슬롯을 비우고 front = rear = -1로 설정했습니다.')
        result = {'initialized': True}
    elif op == 'push':
        if state['size'] == CAPACITY:
            raise QueueError('QUEUE_FULL', '큐가 가득 차 push할 수 없습니다.')
        slot = push_one(state, payload.value)
        step('push 완료', f'{payload.value}를 물리 슬롯 {slot}에 삽입했습니다.', [slot])
        result = {'value': payload.value, 'physical_index': slot}
    elif op == 'bulk_push':
        values = payload.values
        if len(values) > CAPACITY - state['size']:
            raise QueueError('QUEUE_FULL', '남은 슬롯보다 입력 배열이 큽니다. 일괄 삽입을 취소했습니다.')
        slots = []
        for i, value in enumerate(values):
            slot = push_one(state, value)
            slots.append(slot)
            step(f'{i + 1}/{len(values)} push', f'배열[{i}] = {value} → 물리 슬롯 {slot}', [slot])
        result = {'inserted': len(values), 'values': values, 'physical_indexes': slots}
    elif op == 'pop':
        if state['size'] == 0:
            raise QueueError('QUEUE_EMPTY', '큐가 비어 있어 pop할 수 없습니다.')
        slot = state['front']
        value = state['buffer'][slot]
        step('Front 조회', f'제거할 값: {value} (물리 슬롯 {slot})', [slot])
        state['buffer'][slot] = None
        state['size'] -= 1
        if state['size'] == 0:
            state['front'] = state['rear'] = -1
        else:
            state['front'] = (slot + 1) % CAPACITY
        step('pop 완료', f'{value} 제거 및 Front 갱신 완료.', [state['front']] if state['size'] else [])
        result = {'popped': value, 'previous_physical_index': slot}
    elif op == 'size':
        result = {'size': state['size'], 'capacity': CAPACITY}
        step('크기 반환', f'현재 데이터 개수는 {state["size"]}개입니다.')
    elif op == 'status':
        result = {'empty': state['size'] == 0, 'full': state['size'] == CAPACITY,
                  'status': 'EMPTY' if state['size'] == 0 else 'FULL' if state['size'] == CAPACITY else 'NORMAL'}
        step('상태 검사', f'empty={result["empty"]}, full={result["full"]}')
    elif op == 'peek':
        if state['size'] == 0:
            raise QueueError('QUEUE_EMPTY', '큐가 비어 있어 Front 데이터를 확인할 수 없습니다.')
        slot = state['front']
        result = {'value': state['buffer'][slot], 'physical_index': slot}
        step('Front 조회', f'Front 값은 {result["value"]}입니다.', [slot])
    elif op == 'clear':
        removed = state['size']
        state = empty_queue()
        step('전체 삭제', f'{removed}개 데이터를 삭제하고 인덱스를 초기화했습니다.')
        result = {'removed': removed}
    elif op in ('find', 'count', 'contains', 'dump'):
        matches, values = [], []
        for logical, slot in enumerate(ordered_positions(state)):
            value = state['buffer'][slot]
            values.append(value)
            if op != 'dump' and value == payload.value:
                matches.append({'logical_index': logical, 'physical_index': slot})
            step(f'{logical + 1}/{state["size"]} 검색' if op != 'dump' else f'{logical + 1}/{state["size"]} 출력',
                 f'논리 인덱스 {logical} → 물리 슬롯 {slot}, 값 {value}' +
                 (' (일치)' if op != 'dump' and value == payload.value else ''), [slot])
            if op == 'contains' and matches:
                break  # Exists query can stop at its first match.
        if op == 'find':
            result = {'value': payload.value, 'index': matches[0]['logical_index'] if matches else -1,
                      'indexes': [m['logical_index'] for m in matches], 'matches': matches}
        elif op == 'count':
            result = {'value': payload.value, 'count': len(matches)}
        elif op == 'contains':
            result = {'value': payload.value, 'exists': bool(matches)}
        else:
            result = {'values': values, 'size': state['size']}
        step('연산 결과 확정', f'{op} 결과를 산출했습니다.')
    # Defensively revalidate the final snapshot after every operation.
    QueueState.model_validate(state)
    return {'ok': True, 'operation': op, 'result': result,
            'state': state, 'steps': steps,
            'complexity': {'time': COMPLEXITIES[op][0], 'space': COMPLEXITIES[op][1]}}


@app.after_request
def apply_cors(response):
    """CORS supports direct clients; GAS server-side fetch does not need it."""
    origin = request.headers.get('Origin', '')
    allowed = os.environ.get('ALLOWED_ORIGINS', '*').strip()
    origins = [item.strip() for item in allowed.split(',')]
    if allowed == '*':
        response.headers['Access-Control-Allow-Origin'] = '*'
    elif origin in origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS, GET'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.get('/health')
def health():
    return jsonify({'ok': True, 'service': 'fixed-size-queue', 'capacity': CAPACITY})


@app.route('/api/queue', methods=['POST', 'OPTIONS'])
def queue_api():
    if request.method == 'OPTIONS':
        return '', 204
    if request.content_length and request.content_length > 16384:
        return jsonify({'ok': False, 'code': 'REQUEST_TOO_LARGE', 'error': '요청이 너무 큽니다.'}), 413
    try:
        body = request.get_json(silent=True)
        payload = QueueRequest.model_validate(body)
        return jsonify(execute(payload))
    except ValidationError as exc:
        issues = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']}
                  for e in exc.errors(include_context=False, include_url=False)]
        return jsonify({'ok': False, 'code': 'VALIDATION_ERROR',
                        'error': '입력값 또는 큐 스냅샷 검증 실패', 'details': issues}), 422
    except QueueError as exc:
        return jsonify({'ok': False, 'code': exc.code, 'error': str(exc)}), 409


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))
