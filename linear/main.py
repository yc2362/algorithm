import os
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
# GAS Web App 등 다른 출처에서의 요청을 허용하기 위해 CORS 설정
CORS(app)

@app.route('/linear-search', methods=['POST'])
def linear_search():
    """
    선형검색 알고리즘을 수행하고 모든 실행 과정을 단계별로 기록하여 반환합니다.
    
    요청 JSON 구조:
    {
        "array": [10, 20, 30, 40, 50],
        "target": 30
    }
    """
    data = request.get_json()
    
    # 예외 처리: 데이터 유효성 검사
    if not data or 'array' not in data or 'target' not in data:
        return jsonify({
            "success": False,
            "error": "잘못된 요청 형식입니다. 'array'와 'target' 필드가 필요합니다."
        }), 400

    try:
        arr = [int(x) for x in data['array']]
        target = int(data['target'])
    except ValueError:
        return jsonify({
            "success": False,
            "error": "배열 요소와 검색 대상은 모두 정수여야 합니다."
        }), 400

    steps = []
    found_index = -1

    # 선형검색 수행 및 단계별 상태 기록
    for i in range(len(arr)):
        current_value = arr[i]
        is_match = (current_value == target)
        
        # 각 비교 시점의 상세 상태 추적
        steps.append({
            "step": i + 1,
            "current_index": i,
            "current_value": current_value,
            "target": target,
            "is_match": is_match,
            "description": f"단계 {i + 1}: 인덱스 {i}의 값({current_value})과 검색 값({target}) 비교 -> {'일치' if is_match else '불일치'}"
        })

        if is_match:
            found_index = i
            break  # 값 탐색 성공 시 검색 종료

    return jsonify({
        "success": True,
        "array": arr,
        "target": target,
        "found_index": found_index,
        "total_steps": len(steps),
        "complexity": {
            "time_best": "O(1)",
            "time_worst": "O(N)",
            "time_average": "O(N)",
            "space": "O(1)"
        },
        "steps": steps
    })

if __name__ == '__main__':
    # Cloud Run 환경 변수 PORT 지원 (기본값 8080)
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
