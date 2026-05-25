FROM python:3.11-slim

# Tesseract OCR (한국어+영어) + PDF 렌더링용 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-kor \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 (캐싱)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드
COPY . .

# Render가 주입할 PORT 환경변수로 바인딩
ENV PYTHONUNBUFFERED=1
EXPOSE 10000

CMD gunicorn api.app:app --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 180 --preload
