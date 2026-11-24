"""Verify the pinned Python presentation runtime before accepting paid jobs."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ppt_native_service import artifact_root, check_runtime, run_program, font_directory
from app.services.ppt_skill_service import skill_contract


def render_smoke(work: Path) -> dict:
    """Exercise actual native export and Chinese rendering, with no AI/DB call."""
    from app.core.config import settings
    from app.schemas.presentation import PptPage
    from app.services.ppt_native_service import PptNativeService
    from app.services.ppt_workflow_service import PptWorkflowService
    design = {"background": "FFFFFF", "text": "162033", "accent": "B32135"}
    slides = []
    for index in range(2):
        page = PptPage(layout="title" if index == 0 else "summary", title="中文课件运行检查",
                       takeaway="核验原生文字与实际成品渲染", bullets=["检查中文字体和逐页预览"],
                       speaker_notes="公开合成依赖检查，不调用模型。", evidence_refs=[])
        slides.append({**page.model_dump(), "svg": PptWorkflowService._fixture_svg(page, design)})
    previous = settings.generated_artifact_directory
    try:
        settings.generated_artifact_directory = str(work / "smoke")
        artifact, data = PptNativeService(0).export({"title": "中文课件运行检查", "design": design, "slides": slides}, [])
        return {"passed": data["quality_report"]["passed"], "pages": artifact["slide_count"], "paid_requests": 0}
    finally:
        settings.generated_artifact_directory = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-smoke", action="store_true", help="使用临时合成材料实际导出、渲染两页中文课件，不调用 AI 或数据库")
    args = parser.parse_args()
    ready = check_runtime()
    root = artifact_root()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ppt-runtime-check-", dir=root) as temporary:
        work = Path(temporary)
        (work / "probe").write_text("ok", encoding="utf-8")
        version = run_program([ready["office"], "--version"], cwd=work).strip()
        fc_match = shutil.which("fc-match")
        if font_directory():
            font = f"Noto Sans CJK SC ({font_directory()})"
        elif fc_match:
            font = run_program([fc_match, "-f", "%{family}", "Noto Sans CJK SC"], cwd=work).strip()
            if "Noto Sans CJK" not in font:
                raise SystemExit("缺少 Noto Sans CJK 中文字体，请安装 fonts-noto-cjk")
        else:
            font = "fontconfig unavailable; visually verify Chinese rendering"
        smoke = render_smoke(work) if args.render_smoke else None
    print(json.dumps({**ready, "skill": skill_contract()[0], "office_version": version, "font": font,
        "artifact_directory": str(root), "writable": True, "render_smoke": smoke}, ensure_ascii=False))


if __name__ == "__main__":
    main()
