"""Application adapter for the pinned, complete PPT Master skill package.

The web app is not a Codex shell session: it owns authentication, model calls,
confirmation and file permissions. Do not pretend to implement every upstream
interactive route. Load the actual shared design baseline for page generation
and retain the full original skill package for development and deployment.
"""
from functools import lru_cache
import json
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.services.ppt_native_service import runtime_root


@lru_cache(maxsize=4)
def _read_contract(root: str) -> tuple[dict, str]:
    path = Path(root)
    entry = (path / "SKILL.md").read_text(encoding="utf-8")
    lock = json.loads((BACKEND_DIR / "presentation_runtime/ppt-master.lock.json").read_text())
    if "name: ppt-master" not in entry or f'version: "{lock["version"]}"' not in entry:
        raise RuntimeError("PPT Master 技能入口与锁定版本不一致")
    reference = (path / "references/shared-standards-core.md").read_text(encoding="utf-8")
    marker = "## 6. Shared Aesthetic Baseline"
    if marker not in reference:
        raise RuntimeError("PPT Master 设计参考缺失")
    # An explicit adapter projection, not a substitute or modified upstream file.
    baseline = reference[reference.index(marker):]
    return ({"name": "ppt-master", "version": lock["version"], "commit": lock["commit"],
        "license": lock["license"], "entry": "SKILL.md", "integration": "application-svg-adapter",
        "design_reference": "references/shared-standards-core.md#6"}, baseline)


def skill_contract() -> tuple[dict, str]:
    return _read_contract(str(runtime_root()))
