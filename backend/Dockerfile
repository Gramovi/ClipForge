# ClipForge backend image (API + workers)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 \
    SHARED_DIR=/app/shared DATA_DIR=/data WHISPER_MODELS_DIR=/models/whisper HF_HOME=/models/hf \
    FACE_MODEL_PATH=/app/models/face_landmarker.task YUNET_MODEL_PATH=/app/models/face_detection_yunet_2023mar.onnx

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fontconfig fonts-noto-color-emoji fonts-dejavu-core libgl1 libglib2.0-0 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# optional extra CA certificates (corporate TLS proxies) – see certs/README.md
COPY certs/ /tmp/certs/
RUN for f in /tmp/certs/*.crt; do [ -f "$f" ] && cp "$f" /usr/local/share/ca-certificates/; done; update-ca-certificates >/dev/null 2>&1; rm -rf /tmp/certs
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app/backend
COPY backend/requirements.txt backend/requirements-mediapipe.txt ./
RUN pip install -r requirements.txt && pip install --no-deps -r requirements-mediapipe.txt

# face models (MediaPipe landmarker for mouth movement, OpenCV YuNet detector)
RUN mkdir -p /app/models \
 && curl -fsSL -o /app/models/face_landmarker.task \
      https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
 && curl -fsSL -o /app/models/face_detection_yunet_2023mar.onnx \
      https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

COPY shared /app/shared
RUN mkdir -p /usr/local/share/fonts/clipforge && cp /app/shared/fonts/*.ttf /usr/local/share/fonts/clipforge/ && fc-cache -f
COPY backend /app/backend

RUN useradd -m -u 1000 clipforge && mkdir -p /data /models && chown -R clipforge /data /models /app
USER clipforge

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
