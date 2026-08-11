"""从人工标注 JSON 文件计算教材匹配离线指标。

输入是 JSON 数组，每项格式：
{
  "case_id": "law-001",
  "expected_chapter_ids": [9],
  "predicted_chapter_ids": [9],
  "evidence": [{"is_correct": true, "is_cross_chapter": false}]
}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.material_matching_evaluation import (
    EvidenceEvaluation,
    MatchingEvaluationCase,
    evaluate_matching_cases,
)


def load_cases(path: Path) -> list[MatchingEvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("评估文件根节点必须是 JSON 数组")
    return [
        MatchingEvaluationCase(
            case_id=str(item["case_id"]),
            expected_chapter_ids={int(value) for value in item.get("expected_chapter_ids", [])},
            predicted_chapter_ids=[int(value) for value in item.get("predicted_chapter_ids", [])],
            evidence=[EvidenceEvaluation(**evidence) for evidence in item.get("evidence", [])],
        )
        for item in payload
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="计算教材章节与政策差异匹配离线指标")
    parser.add_argument("dataset", type=Path, help="人工标注与模型预测 JSON 文件")
    args = parser.parse_args()
    print(json.dumps(evaluate_matching_cases(load_cases(args.dataset)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
