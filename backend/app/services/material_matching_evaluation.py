from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvidenceEvaluation:
    is_correct: bool
    is_cross_chapter: bool = False


@dataclass(frozen=True)
class MatchingEvaluationCase:
    case_id: str
    expected_chapter_ids: set[int]
    predicted_chapter_ids: list[int]
    evidence: list[EvidenceEvaluation] = field(default_factory=list)


def evaluate_matching_cases(cases: list[MatchingEvaluationCase]) -> dict[str, float | int]:
    """计算稳定的离线指标；无预测案例不进入 Precision 分母。"""
    predicted_cases = [case for case in cases if case.predicted_chapter_ids]
    relevant_cases = [case for case in cases if case.expected_chapter_ids]
    top1_correct = sum(
        case.predicted_chapter_ids[0] in case.expected_chapter_ids
        for case in predicted_cases
    )
    recall_sum = sum(
        len(set(case.predicted_chapter_ids[:3]) & case.expected_chapter_ids)
        / len(case.expected_chapter_ids)
        for case in relevant_cases
    )
    evidence = [item for case in cases for item in case.evidence]
    correct_evidence = sum(item.is_correct for item in evidence)
    cross_chapter = sum(item.is_cross_chapter for item in evidence)
    no_match_cases = [case for case in cases if not case.expected_chapter_ids]
    no_match_correct = sum(not case.predicted_chapter_ids for case in no_match_cases)
    return {
        "case_count": len(cases),
        "evidence_count": len(evidence),
        "chapter_precision_at_1": top1_correct / len(predicted_cases) if predicted_cases else 1.0,
        "chapter_recall_at_3": recall_sum / len(relevant_cases) if relevant_cases else 1.0,
        "evidence_pair_accuracy": correct_evidence / len(evidence) if evidence else 1.0,
        "cross_chapter_mismatch_rate": cross_chapter / len(evidence) if evidence else 0.0,
        "no_match_accuracy": no_match_correct / len(no_match_cases) if no_match_cases else 1.0,
    }
