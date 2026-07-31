from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
from uuid import uuid4
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.presentation_template import PresentationTemplate
from app.models.user import User
from app.schemas.agent import PresentationTemplateData


DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": DRAWING_NS, "p": PRESENTATION_NS}


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", value).strip(" ._")
    return cleaned[:120] or "presentation-template.pptx"


def _hex_from_color_node(node: ElementTree.Element | None) -> str | None:
    if node is None or not list(node):
        return None
    color = list(node)[0]
    for candidate in (color.attrib.get("val"), color.attrib.get("lastClr")):
        if candidate and re.fullmatch(r"[0-9A-Fa-f]{6}", candidate):
            return candidate.upper()
    return None


def inspect_pptx_template(content: bytes) -> dict:
    try:
        archive = ZipFile(BytesIO(content))
    except BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件不是有效的 PPTX",
        ) from exc
    names = set(archive.namelist())
    if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PPTX 结构不完整")
    slide_names = sorted(
        name
        for name in names
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
    )
    presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
    slide_size = presentation.find("p:sldSz", NS)
    cx = int(slide_size.attrib.get("cx", "12192000")) if slide_size is not None else 12192000
    cy = int(slide_size.attrib.get("cy", "6858000")) if slide_size is not None else 6858000
    ratio = cx / cy if cy else 16 / 9
    aspect_ratio = "16:9" if abs(ratio - 16 / 9) < 0.05 else "4:3" if abs(ratio - 4 / 3) < 0.05 else f"{ratio:.2f}:1"

    colors: dict[str, str] = {}
    fonts: dict[str, str] = {}
    theme_names = sorted(name for name in names if name.startswith("ppt/theme/theme") and name.endswith(".xml"))
    if theme_names:
        theme = ElementTree.fromstring(archive.read(theme_names[0]))
        scheme = theme.find(".//a:clrScheme", NS)
        if scheme is not None:
            for child in list(scheme):
                role = child.tag.rsplit("}", 1)[-1]
                value = _hex_from_color_node(child)
                if value:
                    colors[role] = value
        major = theme.find(".//a:fontScheme/a:majorFont/a:latin", NS)
        minor = theme.find(".//a:fontScheme/a:minorFont/a:latin", NS)
        if major is not None and major.attrib.get("typeface"):
            fonts["heading"] = major.attrib["typeface"]
        if minor is not None and minor.attrib.get("typeface"):
            fonts["body"] = minor.attrib["typeface"]

    layout_names: list[str] = []
    for name in sorted(
        item
        for item in names
        if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", item)
    ):
        try:
            layout = ElementTree.fromstring(archive.read(name))
        except ElementTree.ParseError:
            continue
        common = layout.find("p:cSld", NS)
        layout_names.append(
            (common.attrib.get("name") if common is not None else None)
            or Path(name).stem
        )

    palette = {
        "background": colors.get("lt1") or colors.get("lt2") or "F7F4EE",
        "surface": colors.get("lt2") or colors.get("lt1") or "FFFFFF",
        "primary": colors.get("accent1") or colors.get("dk2") or "9E2335",
        "secondary": colors.get("accent2") or colors.get("dk1") or "2459B8",
        "accent": colors.get("accent3") or colors.get("accent4") or "D3A23A",
        "text": colors.get("dk1") or colors.get("dk2") or "172033",
        "muted": colors.get("accent5") or "758198",
        "inverse": colors.get("lt1") or "FFFFFF",
    }
    return {
        "slide_count": len(slide_names),
        "aspect_ratio": aspect_ratio,
        "palette": palette,
        "raw_colors": colors,
        "fonts": fonts,
        "layout_names": layout_names[:40],
        "compatibility": "style_reference",
        "compatibility_note": "已提取主题与版式清单；当前生成继承视觉约束，不直接复制复杂动画和母版对象。",
    }


class PresentationTemplateService:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user
        root = Path(settings.generated_artifact_directory)
        if not root.is_absolute():
            root = (BACKEND_DIR / root).resolve()
        self.root = root / "presentation_templates"
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def serialize(item: PresentationTemplate) -> PresentationTemplateData:
        return PresentationTemplateData.model_validate(item, from_attributes=True)

    def list(self) -> list[PresentationTemplateData]:
        query = select(PresentationTemplate).order_by(PresentationTemplate.id.desc())
        if self.user.role != "admin":
            query = query.where(
                or_(
                    PresentationTemplate.owner_id == self.user.id,
                    PresentationTemplate.is_shared.is_(True),
                )
            )
        return [self.serialize(item) for item in self.db.scalars(query).all()]

    def get_accessible(self, template_id: int) -> PresentationTemplate:
        item = self.db.get(PresentationTemplate, template_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PPT 模板不存在")
        if (
            self.user.role != "admin"
            and item.owner_id != self.user.id
            and not item.is_shared
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该 PPT 模板")
        return item

    def create(
        self,
        *,
        name: str,
        description: str | None,
        is_shared: bool,
        original_filename: str,
        content: bytes,
    ) -> PresentationTemplateData:
        if not original_filename.lower().endswith(".pptx"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 .pptx 模板")
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模板文件为空")
        if len(content) > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"模板不能超过 {settings.max_upload_size_mb}MB",
            )
        metadata = inspect_pptx_template(content)
        if metadata["slide_count"] < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模板至少需要一页")
        shared = bool(is_shared and self.user.role == "admin")
        owner_dir = self.root / str(self.user.id)
        owner_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}_{_safe_filename(original_filename)}"
        path = owner_dir / filename
        path.write_bytes(content)
        item = PresentationTemplate(
            owner_id=self.user.id,
            name=name.strip()[:120],
            description=(description or "").strip()[:1000] or None,
            original_filename=_safe_filename(original_filename),
            storage_path=str(path.relative_to(self.root)),
            status="ready",
            is_shared=shared,
            slide_count=metadata["slide_count"],
            aspect_ratio=metadata["aspect_ratio"],
            theme_data=metadata,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return self.serialize(item)

    def delete(self, template_id: int) -> None:
        item = self.get_accessible(template_id)
        if self.user.role != "admin" and item.owner_id != self.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能删除自己上传的模板")
        path = (self.root / item.storage_path).resolve()
        if self.root.resolve() in path.parents:
            path.unlink(missing_ok=True)
        self.db.delete(item)
        self.db.commit()

    def prompt_reference(self, template_id: int | None) -> dict:
        if template_id is None:
            return {}
        item = self.get_accessible(template_id)
        return {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "aspect_ratio": item.aspect_ratio,
            **json.loads(json.dumps(item.theme_data or {}, ensure_ascii=False)),
        }
