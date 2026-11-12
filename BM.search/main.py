"""
보이어-무어(Boyer-Moore) 문자열 검색 알고리즘 시각화 백엔드 서버 (main.py - FastAPI)
-----------------------------------------------------------------------
- 나쁜 문자표(Bad Character Heuristic, Δ1)와 착한 접미부(Good Suffix Heuristic, Δ2)의
  수행 절차를 단계별(Step)로 추적하여 동시 비교 및 히스토그램 스냅샷 데이터 생성.
- 각 단계별 소요 시간, 시간 복잡도(O(n/m) ~ O(n*m)), 연산 횟수(비교 횟수, 이동 거리 등)를 반환.
"""

import time
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Boyer-Moore Search Visualizer API",
    description="보이어-무어 알고리즘의 나쁜 문자표(Δ1)와 착한 접미부(Δ2) 단계별 비교 시각화 API",
    version="1.0.0"
)

# CORS 설정 (Google Apps Script 웹 앱 및 로컬 브라우저 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    text: Optional[str] = None
    pattern: Optional[str] = None

# --- 1. 전처리 함수: 나쁜 문자표 (Bad Character Table - Δ1) ---
def build_bad_char_table(pattern: str) -> Dict[str, int]:
    """
    각 문자의 패턴 내 마지막 등장 인덱스를 기록 (0-indexed)
    """
    table = {}
    for i, ch in enumerate(pattern):
        table[ch] = i
    return table

# --- 2. 전처리 함수: 착한 접미부표 (Good Suffix Table - Δ2) ---
def build_good_suffix_table(pattern: str) -> List[int]:
    """
    착한 접미부 규칙에 따른 이동 거리 테이블 계산 (Standard Boyer-Moore Suffix / Border)
    shift[j + 1]: 인덱스 j에서 불일치가 발생했을 때의 착한 접미부 도약 거리
    """
    m = len(pattern)
    # suff[i]: pattern과 pattern[0..i]의 최장 공통 접미부(Common Suffix) 길이
    suff = [0] * m
    suff[m - 1] = m
    g = m - 1
    f = m - 1
    for i in range(m - 2, -1, -1):
        if i > g and suff[i + m - 1 - f] < i - g:
            suff[i] = suff[i + m - 1 - f]
        else:
            if i < g:
                g = i
            f = i
            while g >= 0 and pattern[g] == pattern[g + m - 1 - f]:
                g -= 1
            suff[i] = f - g

    shift = [m] * (m + 1)
    
    # Case 2: 접두부와 겹치는 경계(Prefix Border)가 존재하는 경우
    j = 0
    for i in range(m - 1, -2, -1):
        if i == -1 or suff[i] == i + 1:
            while j < m - 1 - i:
                if shift[j] == m:
                    shift[j] = m - 1 - i
                j += 1

    # Case 1: 일치한 접미부가 패턴의 다른 위치에 존재하는 경우
    for i in range(m - 1):
        shift[m - 1 - suff[i]] = m - 1 - i

    return shift

# --- 3. 보이어-무어 단계별 스냅샷 생성 엔진 ---
def generate_boyer_moore_history(text: str, pattern: str) -> Dict[str, Any]:
    n = len(text)
    m = len(pattern)
    
    bad_char_table = build_bad_char_table(pattern)
    good_suffix_table = build_good_suffix_table(pattern)
    
    history = []
    comparisons = 0
    total_shifts = 0
    matches_found = []
    
    start_time = time.perf_counter()
    
    i = 0  # text 내 pattern 시작 위치
    step_num = 0
    
    while i <= n - m:
        j = m - 1  # 우측에서 좌측으로 비교 (Right-to-Left)
        aligned_comparisons = []
        mismatch_info = None
        
        while j >= 0:
            comparisons += 1
            t_char = text[i + j]
            p_char = pattern[j]
            is_match = (t_char == p_char)
            aligned_comparisons.append({
                "text_idx": i + j,
                "pattern_idx": j,
                "text_char": t_char,
                "pattern_char": p_char,
                "is_match": is_match
            })
            
            if not is_match:
                # 불일치 발생
                last_pos = bad_char_table.get(t_char, -1)
                d1 = max(1, j - last_pos)
                d2 = good_suffix_table[j + 1]
                adopted_shift = max(d1, d2)
                selected_rule = "good_suffix" if d2 > d1 else ("bad_char" if d1 > d2 else "equal")
                
                mismatch_info = {
                    "mismatch_j": j,
                    "mismatch_text_idx": i + j,
                    "mismatch_char": t_char,
                    "pattern_char": p_char,
                    "last_occurrence_in_pattern": last_pos,
                    "d1_bad_char": d1,
                    "d2_good_suffix": d2,
                    "adopted_shift": adopted_shift,
                    "selected_rule": selected_rule
                }
                break
            j -= 1
        
        step_num += 1
        elapsed_us = round((time.perf_counter() - start_time) * 1_000_000, 2)
        
        # 완전 일치(Match) 여부
        is_full_match = (j < 0)
        if is_full_match:
            matches_found.append(i)
            d1 = 1
            d2 = good_suffix_table[0] if len(good_suffix_table) > 0 else 1
            adopted_shift = max(d1, d2)
            selected_rule = "good_suffix" if d2 >= d1 else "bad_char"
            mismatch_info = {
                "mismatch_j": -1,
                "mismatch_text_idx": -1,
                "mismatch_char": "",
                "pattern_char": "",
                "last_occurrence_in_pattern": -1,
                "d1_bad_char": d1,
                "d2_good_suffix": d2,
                "adopted_shift": adopted_shift,
                "selected_rule": selected_rule
            }
        
        # 단계별 히스토그램(비교/이동 거리) 데이터 구성
        histogram_data = [
            {"label": "Bad Char (d1)", "value": mismatch_info["d1_bad_char"], "color": "#c0c1ff"},
            {"label": "Good Suffix (d2)", "value": mismatch_info["d2_good_suffix"], "color": "#4edea3"},
            {"label": "Adopted Leap", "value": mismatch_info["adopted_shift"], "color": "#4cd7f6"}
        ]
        
        # 시간 복잡도 추정값
        # Best case: O(n/m), Worst case: O(n*m)
        progress_ratio = min(1.0, (i + m) / n)
        est_complexity = "O(n/m)" if (comparisons / max(1, step_num)) <= 2 else "O(n)"
        
        history.append({
            "step": step_num,
            "window_index": i,
            "window_range": [i, i + m - 1],
            "aligned_comparisons": aligned_comparisons,
            "mismatch_info": mismatch_info,
            "is_full_match": is_full_match,
            "histogram": histogram_data,
            "elapsed_time_us": elapsed_us,
            "complexity_progress": f"{est_complexity} (Step {step_num})",
            "progress_ratio": round(progress_ratio * 100, 1),
            "metrics": {
                "comparisons": comparisons,
                "shifts": total_shifts,
                "current_shift": mismatch_info["adopted_shift"]
            }
        })
        
        total_shifts += mismatch_info["adopted_shift"]
        i += mismatch_info["adopted_shift"]
        
    return {
        "text": text,
        "pattern": pattern,
        "text_length": n,
        "pattern_length": m,
        "bad_char_table": bad_char_table,
        "good_suffix_table": good_suffix_table,
        "total_steps": len(history),
        "total_comparisons": comparisons,
        "total_shifts": total_shifts,
        "matches_found": matches_found,
        "history": history
    }

# --- 4. 엔드포인트 정의 ---
@app.get("/")
def root():
    return {
        "service": "Boyer-Moore Search Visualizer API (FastAPI)",
        "algorithm": "Boyer-Moore (Bad Character + Good Suffix)",
        "endpoints": {
            "health": "GET /health",
            "search": "POST /api/search or GET /api/search"
        }
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Boyer-Moore Search Visualizer API (FastAPI)",
        "timestamp": time.time()
    }

@app.api_route("/api/search", methods=["GET", "POST"])
def execute_search(req: Optional[SearchRequest] = None):
    try:
        text = "ABAABCACAC"
        pattern = "ABAC"
        
        if req:
            if req.text and req.text.strip():
                text = req.text.strip()
            if req.pattern and req.pattern.strip():
                pattern = req.pattern.strip()
                
        if len(pattern) == 0:
            raise HTTPException(status_code=400, detail="검색 패턴은 최소 1글자 이상이어야 합니다.")
        if len(pattern) > len(text):
            raise HTTPException(status_code=400, detail="패턴의 길이는 타겟 텍스트보다 길 수 없습니다.")
        if len(text) > 200:
            raise HTTPException(status_code=400, detail="시각화 품질을 위해 텍스트 길이는 200자 이하로 제한됩니다.")
            
        result = generate_boyer_moore_history(text, pattern)
        
        return {
            "status": "success",
            "metadata": {
                "name": "보이어-무어 문자열 검색 (Boyer-Moore Search)",
                "time_complexity": "Best O(n/m), Worst O(n·m)",
                "space_complexity": "O(|Σ| + m)",
                "description": "우측에서 좌측으로 비교하며 나쁜 문자표(Δ1)와 착한 접미부(Δ2)의 최대 도약 거리를 선택하여 부분 선형(Sublinear) 탐색 수행"
            },
            "data": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 내부 처리 오류: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main.py:app", host="0.0.0.0", port=8080, reload=True)
