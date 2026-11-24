FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GENERATED_ARTIFACT_DIRECTORY=/app/knowledge/generated_artifacts
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
# Final PPTX rendering is mandatory. Frontend builds stay in local/CI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk libreoffice-impress poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY presentation_runtime/ppt-master.lock.json ./presentation_runtime/ppt-master.lock.json
# Full pinned distribution, verified by the installer; no model-generated code.
RUN python scripts/install_ppt_master.py
RUN mkdir -p /app/data /app/knowledge/uploads /app/knowledge/ai_media \
        /app/knowledge/chroma /app/knowledge/generated_artifacts \
    && chown -R app:app /app
USER app
RUN python scripts/verify_presentation_runtime.py --render-smoke
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
