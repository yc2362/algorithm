# Cloud Run의 Linux x86_64 환경에서 사용할 경량 Python 런타임.
FROM python:3.12-slim

# 파이썬 바이트코드 생성을 생략하고 컨테이너 로그를 즉시 출력한다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app

# 의존성을 먼저 복사하여 소스 변경 시 빌드 캐시를 재사용한다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 서비스 구동에 필요한 코드만 포함한다.
COPY main.py ./

# 루트 권한 대신 비특권 사용자로 애플리케이션 실행.
RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8080

# Cloud Run이 지정하는 PORT 값을 셸에서 확장한다.
# 단일 worker가 여러 요청을 동시에 처리하더라도 상태는 요청별 객체로 독립적이다.
CMD exec gunicorn --bind :${PORT} --workers 1 --threads 8 --timeout 60 main:app
