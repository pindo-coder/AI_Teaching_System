"""验证教学成果容器运行时及生成目录写权限。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


BACKEND_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = BACKEND_DIR / "presentation_runtime"
RENDER_SCRIPT = RUNTIME_DIR / "render_pptx.mjs"


def _configured_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default))
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def main() -> None:
    node_setting = os.getenv("PRESENTATION_NODE_BINARY", "node")
    node_binary = shutil.which(node_setting)
    if node_binary is None:
        candidate = Path(node_setting)
        if candidate.is_file():
            node_binary = str(candidate)
    if node_binary is None:
        raise SystemExit(f"未找到 Node.js：{node_setting}")

    version = subprocess.run(
        [node_binary, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    matched = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
    if matched is None or int(matched.group(1)) < 24:
        raise SystemExit(f"教学成果运行时要求受支持的 Node.js 24+，当前为 {version}")

    if not RENDER_SCRIPT.is_file():
        raise SystemExit(f"缺少 PPT 渲染脚本：{RENDER_SCRIPT}")
    node_modules = _configured_path(
        "PRESENTATION_NODE_MODULES",
        str(RUNTIME_DIR / "node_modules"),
    )
    if not (node_modules / "pptxgenjs").exists():
        raise SystemExit(f"缺少生产依赖 pptxgenjs：{node_modules}")

    environment = os.environ.copy()
    environment["NODE_PATH"] = os.pathsep.join(
        value
        for value in (str(node_modules), environment.get("NODE_PATH", ""))
        if value
    )
    subprocess.run([node_binary, "--check", str(RENDER_SCRIPT)], check=True)
    subprocess.run(
        [node_binary, "--input-type=module", "--eval", "await import('pptxgenjs')"],
        cwd=RUNTIME_DIR,
        env=environment,
        check=True,
    )

    artifact_directory = _configured_path(
        "GENERATED_ARTIFACT_DIRECTORY",
        "../knowledge_base/generated_artifacts",
    )
    artifact_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".runtime-write-check-",
        dir=artifact_directory,
        delete=True,
    ) as probe:
        probe.write("ok")
        probe.flush()

    print(
        json.dumps(
            {
                "node": version,
                "render_script": str(RENDER_SCRIPT),
                "node_modules": str(node_modules),
                "artifact_directory": str(artifact_directory),
                "writable": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
