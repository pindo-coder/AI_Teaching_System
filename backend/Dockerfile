FROM node:24-bookworm-slim AS presentation-builder

WORKDIR /runtime

RUN npm install --global pnpm@9.15.9

COPY presentation_runtime/package.json presentation_runtime/pnpm-lock.yaml ./
RUN pnpm install --prod --frozen-lockfile

COPY presentation_runtime/render_pptx.mjs ./render_pptx.mjs

RUN node --check render_pptx.mjs \
    && node --input-type=module --eval "await import('pptxgenjs')"


FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production \
    GENERATED_ARTIFACT_DIRECTORY=/app/knowledge/generated_artifacts \
    PRESENTATION_NODE_BINARY=/usr/local/bin/node \
    PRESENTATION_NODE_MODULES=/app/presentation_runtime/node_modules

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

# Node 官方二进制在 Debian slim 上需要这些动态链接库；ffprobe 用于
# 服务端核验录音真实时长，避免信任客户端提交的 duration。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libatomic1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY --from=presentation-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=presentation-builder --chown=app:app /runtime ./presentation_runtime

RUN mkdir -p /app/data /app/knowledge/uploads /app/knowledge/ai_media \
        /app/knowledge/chroma /app/knowledge/generated_artifacts \
    && chown -R app:app /app

USER app

# 同时校验 Node、渲染脚本、生产依赖，以及非 root 用户对成果目录的写权限。
RUN python scripts/verify_presentation_runtime.py

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
