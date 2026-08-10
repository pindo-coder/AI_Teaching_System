from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_backend_image_contains_presentation_runtime() -> None:
    dockerfile = _read("backend/Dockerfile")

    assert "FROM node:24-bookworm-slim AS presentation-builder" in dockerfile
    assert "ffmpeg" in dockerfile
    assert "pnpm install --prod --frozen-lockfile" in dockerfile
    assert "COPY presentation_runtime/render_pptx.mjs" in dockerfile
    assert "COPY --from=presentation-builder --chown=app:app /runtime ./presentation_runtime" in dockerfile
    assert "RUN python scripts/verify_presentation_runtime.py" in dockerfile


def test_compose_persists_generated_artifacts_at_configured_path() -> None:
    compose = _read("docker-compose.yml")

    artifact_path = "/app/knowledge/generated_artifacts"
    assert f"GENERATED_ARTIFACT_DIRECTORY: {artifact_path}" in compose
    assert f"- generated_artifacts:{artifact_path}" in compose
    assert "PRESENTATION_NODE_BINARY: /usr/local/bin/node" in compose
    assert "PRESENTATION_NODE_MODULES: /app/presentation_runtime/node_modules" in compose
    assert "  generated_artifacts:" in compose


def test_production_database_requires_external_mysql_host() -> None:
    compose = _read("docker-compose.yml")
    production_environment = _read(".env.production.example")
    database_url = next(
        line.removeprefix("DATABASE_URL=")
        for line in production_environment.splitlines()
        if line.startswith("DATABASE_URL=")
    )

    assert "DATABASE_URL: ${DATABASE_URL:?" in compose
    assert database_url.startswith("mysql+pymysql://")
    assert "@127.0.0.1" not in database_url
    assert "@localhost" not in database_url
    assert "mysql.example.internal" in database_url


def test_compose_has_configurable_persistent_https_gateway() -> None:
    compose = _read("docker-compose.yml")
    caddyfile = _read("deploy/Caddyfile")
    ip_caddyfile = _read("deploy/Caddyfile.ip")
    ip_proxy_caddyfile = _read("deploy/Caddyfile.ip-proxy")
    production_environment = _read(".env.production.example")
    nginx = _read("frontend/nginx.conf")

    assert "image: caddy:2.11.4-alpine" in compose
    assert 'APP_SITE_ADDRESS: "${APP_SITE_ADDRESS:-:80}"' in compose
    assert '- "443:443"' in compose
    assert "- caddy_data:/data" in compose
    assert "- caddy_config:/config" in compose
    assert "${CADDYFILE_PATH:-./deploy/Caddyfile}:/etc/caddy/Caddyfile:ro" in compose
    assert "APP_SITE_ADDRESS=:80" in production_environment
    assert "CADDYFILE_PATH=./deploy/Caddyfile" in production_environment
    assert "{$APP_SITE_ADDRESS}" in caddyfile
    assert "reverse_proxy frontend:80" in caddyfile
    assert "profile shortlived" in ip_caddyfile
    assert "https://acme-v02.api.letsencrypt.org/directory" in ip_caddyfile
    assert "reverse_proxy frontend:80" in ip_caddyfile
    assert "auto_https disable_redirects" in ip_proxy_caddyfile
    assert "default_sni {$APP_SITE_ADDRESS}" in ip_proxy_caddyfile
    assert "disable_http_challenge" in ip_proxy_caddyfile
    assert "reverse_proxy {$APP_UPSTREAM}" in ip_proxy_caddyfile
    assert "proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;" in nginx
