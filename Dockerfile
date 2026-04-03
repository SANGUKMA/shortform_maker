FROM python:3.11-slim

# FFmpeg + Node.js + curl 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl fontconfig && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 번들 폰트를 시스템 폰트 디렉토리에 등록 (FFmpeg subtitles 필터용)
RUN mkdir -p /usr/share/fonts/truetype/custom && \
    cp fonts/*.ttf /usr/share/fonts/truetype/custom/ 2>/dev/null || true && \
    fc-cache -f

CMD ["python", "app.py"]
