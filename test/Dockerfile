FROM python:3.11-slim

WORKDIR /app

# 캐시 효율화를 위해 requirements.txt 먼저 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 포트 환경변수 기본값 설정 (Cloud Run 등 호환)
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
