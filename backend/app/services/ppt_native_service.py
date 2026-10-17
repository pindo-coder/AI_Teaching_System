"""Pinned PPT Master compiler and real PPTX -> PNG acceptance rendering.

Only allowlisted programs run, with a stripped environment, independent output
directories and hard timeouts. Model-generated programs are never executed.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from copy import deepcopy
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.core.config import BACKEND_DIR, settings
from app.services.ppt_svg_service import SVG_NS, FONT_FAMILY


def artifact_root() -> Path:
    path = Path(settings.generated_artifact_directory)
    return (path if path.is_absolute() else BACKEND_DIR / path).resolve()


def safe_artifact_path(relative: str) -> Path:
    root = artifact_root()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise FileNotFoundError("课件资源不存在或路径越界")
    return path


def runtime_root() -> Path:
    root = Path(settings.ppt_master_directory)
    root = (root if root.is_absolute() else BACKEND_DIR / root).resolve()
    if not (root / "scripts/svg_to_pptx.py").is_file():
        raise RuntimeError("PPT Master 尚未安装，请先运行 scripts/install_ppt_master.py")
    return root


def font_directory() -> Path | None:
    if settings.ppt_font_directory:
        return Path(settings.ppt_font_directory).resolve()
    bundled = BACKEND_DIR / "presentation_runtime/fonts"
    return bundled if bundled.is_dir() else None


def run_program(args: list[str], *, cwd: Path, timeout: int | None = None, font_config: Path | None = None) -> str:
    env = {key: value for key, value in os.environ.items() if key in {
        "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SYSTEMROOT", "WINDIR",
        "FONTCONFIG_FILE", "FONTCONFIG_PATH", "DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH",
    }}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if font_config:
        env["FONTCONFIG_FILE"] = str(font_config)
        env["SAL_FONTPATH_PRIVATE"] = str(font_directory())
    process = subprocess.Popen(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=os.name == "posix")
    try:
        stdout, stderr = process.communicate(timeout=timeout or settings.ppt_export_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise RuntimeError("课件导出或渲染超时，已有成果未被覆盖") from exc
    if process.returncode:
        raise RuntimeError("课件工具检查失败：" + (stderr or stdout)[-1800:])
    return stdout


def check_runtime() -> dict[str, str]:
    runtime = runtime_root()
    office, raster = shutil.which(settings.ppt_office_binary), shutil.which("pdftoppm")
    if not office or not raster:
        raise RuntimeError("课件成品验收需要 LibreOffice 和 Poppler（soffice、pdftoppm）")
    # Fail before paid model calls if the package/attribution gate is broken.
    run_program([sys.executable, str(runtime / "scripts/attribution_guard.py")], cwd=runtime)
    for module in ("pptx", "PIL", "lxml", "yaml", "pathops", "uharfbuzz", "xlsxwriter", "pymupdf"):
        __import__(module)
    directory = font_directory()
    if directory:
        from PIL import ImageFont
        found = False
        for path in directory.glob("*"):
            if path.suffix.lower() not in {".otf", ".ttf", ".ttc"}:
                continue
            try:
                family, _ = ImageFont.truetype(str(path), 24).getname()
                found |= family == FONT_FAMILY
            except OSError:
                continue
        if not found:
            raise RuntimeError("PPT_FONT_DIRECTORY 中没有可加载的 Noto Sans CJK SC 字体")
    elif not settings.ai_mock_mode:
        matcher = shutil.which("fc-match")
        family = run_program([matcher, "-f", "%{family}", FONT_FAMILY], cwd=runtime) if matcher else ""
        if "Noto Sans CJK" not in family:
            raise RuntimeError("缺少 Noto Sans CJK 中文字体，请安装 fonts-noto-cjk 或配置 PPT_FONT_DIRECTORY")
    return {"runtime": str(runtime), "office": office, "raster": raster}


def apply_picture_frame(root: ET.Element, slot: ET.Element, design: dict) -> str:
    """Trusted, application-owned clipping; raw model SVG cannot add URL refs."""
    shape = design.get("image_frame_shape", "roundRect")
    x, y, width, height = (float(slot.get(key, "0")) for key in ("x", "y", "width", "height"))
    if shape not in {"circle", "roundRect"} or min(width, height) <= 0:
        raise RuntimeError("图片容器形状或尺寸无效")
    if shape == "circle" and abs(width-height) > 1:
        raise RuntimeError("圆形图片容器必须宽高相等")
    # Remove model-made picture frames, not content. Core text/labels are never
    # removed. An enclosing concentric ring is not a second, different frame.
    for parent in list(root.iter()):
        for node in list(parent):
            tag = node.tag.rsplit("}", 1)[-1]
            if tag in {"circle", "ellipse"}:
                cx, cy = float(node.get("cx", "0")), float(node.get("cy", "0"))
                rx = float(node.get("r", node.get("rx", "0")))
                ry = float(node.get("r", node.get("ry", "0")))
                if (abs(cx-x-width/2) <= width*.12 and abs(cy-y-height/2) <= height*.12
                    and rx*2 >= width*.7 and ry*2 >= height*.7
                    and rx*2 <= max(width, height)*1.8 and ry*2 <= max(width, height)*1.8):
                    parent.remove(node)
    clip_id = "app-picture-clip"
    if any(node.get("id") in {clip_id, "app-picture-border"} for node in root.iter()):
        raise RuntimeError("SVG 占用了应用图片容器的保留标识")
    definitions = ET.SubElement(root, f"{{{SVG_NS}}}defs")
    clip = ET.SubElement(definitions, f"{{{SVG_NS}}}clipPath", {"id": clip_id, "clipPathUnits": "userSpaceOnUse"})
    if shape == "circle":
        tag = "circle"
        geometry = {"cx": str(x+width/2), "cy": str(y+height/2), "r": str(width/2)}
    else:
        tag = "rect"
        geometry = {"x": str(x), "y": str(y), "width": str(width), "height": str(height),
                    "rx": str(min(18, width*.05, height*.05)), "ry": str(min(18, width*.05, height*.05))}
    ET.SubElement(clip, f"{{{SVG_NS}}}{tag}", geometry)
    slot.set("clip-path", f"url(#{clip_id})")
    slot.set("preserveAspectRatio", "xMidYMid slice")
    # The border has exactly the clipping geometry, never a separate guessed
    # ellipse around a landscape bitmap. Source pixels remain intact in PPTX.
    color = str(design.get("accent") or "B78334")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", color):
        raise RuntimeError("图片边框颜色无效")
    ET.SubElement(root, f"{{{SVG_NS}}}{tag}", {**geometry, "id": "app-picture-border",
        "fill": "none", "stroke": "#" + color, "stroke-width": "2"})
    return "ellipse" if shape == "circle" else "roundRect"


class PptNativeService:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.root = artifact_root()

    def export(self, ppt_data: dict, evidence: list[dict]) -> tuple[dict, dict]:
        ready = check_runtime()
        runtime, office, raster = Path(ready["runtime"]), ready["office"], ready["raster"]
        revision = uuid4().hex
        project = self.root / str(self.run_id) / "ppt" / revision
        sources, notes, previews = (project / value for value in ("svg_output", "notes", "preview"))
        for path in (sources, notes, previews):
            path.mkdir(parents=True, exist_ok=False)
        data = deepcopy(ppt_data)
        data["revision_id"] = revision
        font_config = None
        directory = font_directory()
        if directory:
            if not directory.is_dir():
                raise RuntimeError("PPT_FONT_DIRECTORY 不存在")
            font_config = project / "fonts.conf"
            fonts = ET.Element("fontconfig")
            ET.SubElement(fonts, "dir").text = str(directory)
            ET.SubElement(fonts, "cachedir").text = str(project / "font-cache")
            font_config.write_text(ET.tostring(fonts, encoding="unicode"), encoding="utf-8")
        for index, page in enumerate(data["slides"]):
            svg = ET.fromstring(page["svg"])
            slot = svg.find(f".//{{{SVG_NS}}}image")
            asset = page.get("visual_asset") or {}
            if slot is not None:
                if asset.get("storage_path"):
                    image = safe_artifact_path(asset["storage_path"])
                    if image.stat().st_size > 20 * 1024 * 1024:
                        raise RuntimeError("课件图片超过 20MB")
                    media = asset.get("media_type", "image/png")
                    if media not in {"image/png", "image/jpeg", "image/webp"}:
                        raise RuntimeError("课件图片类型不受支持")
                    slot.set("href", f"data:{media};base64," + base64.b64encode(image.read_bytes()).decode())
                    apply_picture_frame(svg, slot, data.get("design") or {})
                else:
                    for parent in svg.iter():
                        if slot in list(parent):
                            parent.remove(slot)
                            break
            stem = f"slide-{index+1:02d}"
            (sources / f"{stem}.svg").write_text(ET.tostring(svg, encoding="unicode"), encoding="utf-8")
            citations = []
            for ref in page.get("evidence_refs", []):
                source = evidence[int(ref.removeprefix("资料")) - 1]
                citations.append(f"[{ref}] {source.get('source_title', '')} {source.get('position', '')}")
            if asset.get("storage_path") and slot is not None:
                citations.append(f"配图：{asset.get('model') or 'AI'} 生成的教学辅助意象，不代表真实新闻或历史影像。")
            (notes / f"{stem}.md").write_text(page["speaker_notes"] + "\n\n" + "\n".join(citations), encoding="utf-8")
        run_program([sys.executable, str(runtime / "scripts/svg_quality_checker.py"), str(project),
                     "--quick-generate", "--stage", "final", "--json"], cwd=project)
        quality_file = project / "validation/svg_quality_report.json"
        if not quality_file.is_file():
            raise RuntimeError("课件未产生结构检查报告")
        output = project / "教学课件.pptx"
        run_program([sys.executable, str(runtime / "scripts/svg_to_pptx.py"), str(project),
                     "--quick-generate", "--with-notes", "--no-animations", "-o", str(output)], cwd=project)
        # Upstream maps Noto CJK to Microsoft YaHei for Windows. Keep our
        # application font contract portable instead of depending on that font.
        normalized = output.with_suffix(".fonts.pptx")
        with ZipFile(output) as source, ZipFile(normalized, "w") as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename.startswith("ppt/") and info.filename.endswith(".xml"):
                    # Preserve namespace declarations (including prefixes used
                    # by mc:Ignorable values) and all non-font OOXML verbatim.
                    payload = re.sub(rb'typeface="(?!\+)[^"]*"',
                        ('typeface="' + FONT_FAMILY + '"').encode(), payload)
                target.writestr(info, payload)
        normalized.replace(output)
        # Verify native text and page count, not just a ZIP magic prefix.
        with ZipFile(output) as archive:
            page_names = [name for name in archive.namelist() if __import__('re').fullmatch(r"ppt/slides/slide\d+\.xml", name)]
            if len(page_names) != len(data["slides"]):
                raise RuntimeError("导出页数与确认方案不一致")
            ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            for index, page in enumerate(data["slides"]):
                xml = ET.fromstring(archive.read(f"ppt/slides/slide{index+1}.xml"))
                visible = "".join(node.text or "" for node in xml.findall(".//a:t", ns))
                compact = lambda text: "".join(text.split())
                labels = [value for i, value in enumerate(page.get("diagram_labels", [])) if f'id="label-{i}"' in page["svg"]]
                if any(compact(value) not in compact(visible) for value in [page["title"], page["takeaway"], *page["bullets"], *labels]):
                    raise RuntimeError(f"导出的第 {index+1} 页丢失可编辑正文")
                if page.get("visual_asset") and "visual-asset" in page.get("svg", ""):
                    pictures = xml.findall(".//{http://schemas.openxmlformats.org/presentationml/2006/main}pic")
                    if not pictures:
                        raise RuntimeError(f"第 {index+1} 页配图没有进入最终 PPTX")
                    frame = "ellipse" if data.get("design", {}).get("image_frame_shape") == "circle" else "roundRect"
                    if not any(pic.find(f".//a:prstGeom[@prst='{frame}']", ns) is not None for pic in pictures):
                        raise RuntimeError(f"第 {index+1} 页图片裁切与边框形状不一致")
        profile = project / "office-profile"
        run_program([office, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf",
                     "--outdir", str(previews), str(output)], cwd=project, font_config=font_config)
        pdf = previews / "教学课件.pdf"
        if not pdf.is_file():
            raise RuntimeError("课件最终文件未能渲染，不能宣称生成成功")
        import pymupdf
        with pymupdf.open(pdf) as document:
            if len(document) != len(data["slides"]):
                raise RuntimeError("最终文件渲染页数不一致")
            for index, (rendered, page) in enumerate(zip(document, data["slides"])):
                if any(glyph == 0 for span in rendered.get_texttrace() for char, glyph, *_ in span["chars"]
                       if 0x3400 <= char <= 0x9FFF):
                    raise RuntimeError(f"第 {index+1} 页缺少中文字形，请检查 Noto 中文字体")
                visible = "".join(rendered.get_text().split())
                labels = [value for i, value in enumerate(page.get("diagram_labels", [])) if f'id="label-{i}"' in page["svg"]]
                if any("".join(value.split()) not in visible for value in [page["title"], page["takeaway"], *page["bullets"], *labels]):
                    raise RuntimeError(f"第 {index+1} 页成品渲染遗漏正文，当前成果不予替换")
        run_program([raster, "-png", "-scale-to", "1280", str(pdf), str(previews / "page")], cwd=project)
        images = sorted(previews.glob("page-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
        if len(images) != len(data["slides"]):
            raise RuntimeError("课件最终渲染页数不一致")
        from PIL import Image, ImageStat
        for index, (page, image_path) in enumerate(zip(data["slides"], images)):
            with Image.open(image_path) as image:
                if max(ImageStat.Stat(image.convert("RGB")).stddev) < 1:
                    raise RuntimeError(f"第 {index+1} 页渲染为空白")
            page["preview_path"] = str(image_path.relative_to(self.root))
        data["quality_report"] = {
            "passed": True, "summary": "内容覆盖、SVG 结构、原生文字与成品逐页渲染检查通过；请教师核验教学与视觉效果。",
            "reviewer": "ppt-native-v2", "issues": [],
            "checks": ["content_coverage", "svg_structure", "native_text", "rendered_pages", "rendered_text", "chinese_glyphs"],
            "visual_review": "teacher_required",
        }
        artifact = {
            "kind": "ppt", "title": data["title"], "file_name": re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", data["title"])[:80] + ".pptx",
            "storage_path": str(output.relative_to(self.root)), "revision_id": revision,
            "media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "slide_count": len(data["slides"]), "preview": data,
            "generated_time": datetime.now(timezone.utc).isoformat(),
        }
        return artifact, data
