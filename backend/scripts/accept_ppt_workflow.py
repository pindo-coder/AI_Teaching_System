"""Real configured-provider acceptance using public synthetic teaching material.

Run against an isolated DATABASE_URL and GENERATED_ARTIFACT_DIRECTORY. No notes,
tasks, publications or account settings are changed. Normal AI audit logs apply.
"""
from __future__ import annotations
import argparse
import json
import logging
from xml.etree import ElementTree as ET
from pathlib import Path
from time import monotonic

from app.core.config import settings
import app.db.models  # noqa: F401 -- register all related SQLAlchemy models
from app.services.ai_operation_service import AiProviderConfigService
from app.services.ppt_workflow_service import PptWorkflowService
from app.services.ppt_native_service import PptNativeService
from app.services.ppt_svg_service import bind_plan_text, validate_svg, without_disclosure, SvgValidationError
from app.schemas.presentation import PptPage
from app.schemas.agent import PptPreferences
from app.services.ppt_skill_service import skill_contract


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, choices=range(6, 31), default=6)
    parser.add_argument("--resume-draft", type=Path, help="继续本脚本在隔离目录留下的公开材料草稿")
    parser.add_argument("--resume", action="store_true", help="复用相同输入的未完成检查点")
    parser.add_argument("--images", action="store_true", help="调用真实配置的图像服务")
    parser.add_argument("--topic", choices=["democracy", "culture"], default="democracy")
    parser.add_argument("--frame", choices=["roundRect", "circle"], default="roundRect")
    args = parser.parse_args()
    if settings.ai_mock_mode:
        raise SystemExit("真实验收必须设置 AI_MOCK_MODE=false")
    config = AiProviderConfigService.resolve_for_feature("ppt_plan")
    if "deepseek" not in config.model_name.lower():
        raise SystemExit("请先确认当前文本能力是用户授权测试的 DeepSeek")
    source = {"source_title": "本地验收公开教学材料", "position": "测试材料第1节", "excerpt":
        "全过程人民民主是社会主义民主政治的本质属性，是最广泛、最真实、最管用的民主。"
        "协商民主是实践全过程人民民主的重要形式。基层群众自治体现人民依法直接行使民主权利。"
        "课堂通过模拟社区公共事务协商，区分民主选举、民主协商、民主决策、民主管理、民主监督。"}
    title = "全过程人民民主"
    points = ["基本内涵", "协商民主", "基层实践"]
    question = "如何在社区公共事务中保障有效参与？"
    if args.topic == "culture":
        title = "文化传承与青年表达"
        points = ["理解原文与保留核心内容", "用读书分享连接当代生活", "整理来源并尊重原创"]
        question = "如何组织一次有依据、有交流的校园读书分享？"
        source["excerpt"] = ("本课为公开合成教学活动材料：文化传承首先要理解原有内容，在当代生活中进行合适表达。"
            "以校园读书分享为练习情境，依次阅读、交流、整理、分享，区分原文、个人理解与创作表达。"
            "学生可用书籍、读书笔记和手工作品讲述学习体会，分享前核对引用来源与素材授权。"
            "课堂不引用具体历史事件或统计数字，不把个人创作当作原文。")
    variables = {"course_name": "思想政治理论课", "chapter_title": "全过程人民民主",
        "lesson_hours": "1", "student_level": "本科生", "teaching_goal": "理解基本内涵并分析社区协商实例",
        "outline_json": json.dumps({"title": "全过程人民民主", "key_points": ["基本内涵", "协商民主", "基层实践"],
            "discussion_questions": ["如何在社区公共事务中保障有效参与？"]}, ensure_ascii=False),
        "evidence_context": source["excerpt"], "ppt_preferences": json.dumps({"slide_count": args.pages,
            "include_interaction": True, "include_visuals": False}), "template_reference": "{}"}
    variables.update(chapter_title=title, teaching_goal="理解本专题概念，并依据给定材料分析和设计课堂练习",
        outline_json=json.dumps({"title": title, "key_points": points, "discussion_questions": [question]}, ensure_ascii=False),
        evidence_context=source["excerpt"], ppt_preferences=json.dumps({"slide_count": args.pages,
            "include_interaction": True, "include_visuals": args.images, "image_frame_shape": args.frame}))
    started = monotonic()
    workflow = PptWorkflowService(None, None, (900000 if args.topic == "democracy" else 910000) + args.pages,
        progress=lambda stage, done, total: print(json.dumps({"stage": stage, "done": done, "total": total}), flush=True)
    )
    if args.resume_draft:
        root = Path(settings.generated_artifact_directory).resolve()
        draft = args.resume_draft.resolve()
        if root not in draft.parents:
            raise SystemExit("续测草稿必须位于隔离成果目录内")
        data = json.loads((draft / "plan.json").read_text())
        if len(data["slides"]) != args.pages:
            raise SystemExit("草稿页数与 --pages 不一致")
        workflow.diagnostics = draft
        preferences = PptPreferences.model_validate(data["preferences"])
        retained = 0
        for index, item in enumerate(data["slides"]):
            page = PptPage.model_validate({key: value for key, value in item.items() if key in PptPage.model_fields})
            paths = [draft / f"page-{index+1}.svg.txt", *sorted(draft.glob(f"page-{index+1}-attempt-*.invalid-svg.txt"), reverse=True)]
            for path in paths:
                if not path.is_file():
                    continue
                try:
                    item["svg"] = validate_svg(bind_plan_text(without_disclosure(path.read_text()), page), page)
                    retained += 1
                    break
                except (SvgValidationError, ValueError, ET.ParseError):
                    continue
            else:
                item["svg"] = workflow._design_page(item, data["design"], preferences, index, data["slides"])
                (draft / f"page-{index+1}.svg.txt").write_text(item["svg"], encoding="utf-8")
        print(json.dumps({"retained_pages": retained}), flush=True)
        data["skill"] = skill_contract()[0]
        artifact, data = PptNativeService(workflow.run_id).export(data, [source])
    else:
        artifact, data = workflow.generate(variables, [source], resume=args.resume)
    # These contain only the synthetic acceptance material, never credentials.
    root = Path(settings.generated_artifact_directory).resolve()
    result = {"model": config.model_name, "pages": len(data["slides"]),
        "seconds": round(monotonic()-started, 1), "resumed": bool(args.resume_draft or args.resume), "artifact": artifact["storage_path"],
        "topic": args.topic, "frame": args.frame, "images": data.get("multimodal"),
        "quality": data["quality_report"], "data": data}
    path = root / f"acceptance-{args.topic}-{args.pages}-{args.frame}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "data"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
