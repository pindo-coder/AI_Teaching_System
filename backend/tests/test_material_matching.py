from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from contextlib import nullcontext
from types import ModuleType
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.authority_discovery import MaterialCandidate, MaterialSnapshot
from app.models.chapter import Chapter
from app.models.citation import KnowledgeChunk
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.material_scope import DocumentChapterScope, DocumentCourseScope
from app.services import authority_discovery_service as discovery
from app.services.authority_discovery_service import AuthorityDiscoveryService
from app.services.material_matching_evaluation import (
    EvidenceEvaluation,
    MatchingEvaluationCase,
    evaluate_matching_cases,
)
from app.services.material_matching_service import (
    NliPrediction,
    OptionalOpenSourceMatcher,
    normalize_rrf_scores,
    open_source_matcher,
    reciprocal_rank_fusion,
)


def test_offline_evaluation_cli_runs_without_pythonpath() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(backend_root / "scripts" / "evaluate_material_matching.py"),
            str(backend_root / "tests" / "fixtures" / "material_matching_evaluation.json"),
        ],
        cwd=backend_root,
        check=True,
        capture_output=True,
        text=True,
    )

    metrics = json.loads(result.stdout)
    assert metrics["chapter_precision_at_1"] == 1.0
    assert metrics["cross_chapter_mismatch_rate"] == 0.0


def _candidate(db: Session, *, title: str, content: str) -> MaterialCandidate:
    source = AuthorityDiscoveryService(db).list_sources()[0]
    digest = f"{abs(hash((title, content))):064x}"[-64:]
    candidate = MaterialCandidate(
        source_registry_id=source.id,
        title=title,
        source_url=f"https://www.gov.cn/test/{digest[:12]}",
        canonical_url=f"https://www.gov.cn/test/{digest[:12]}",
        publisher="中国政府网",
        source_level="A",
        recommended_material_type="central",
        status="pending_review",
        content_hash=digest,
        content_preview=content,
        extraction_quality_score=1,
        relevance_score=0.9,
        freshness_score=1,
        novelty_score=1,
    )
    db.add(candidate); db.flush()
    db.add(MaterialSnapshot(
        candidate_id=candidate.id,
        fetched_url=candidate.source_url,
        content=content,
        content_hash=digest,
        fetched_time=discovery._now(),
    ))
    db.commit()
    return candidate


def _curriculum(db: Session) -> tuple[Course, Chapter, Chapter, Chapter]:
    course = Course(name="习近平新时代中国特色社会主义思想概论", description="")
    db.add(course); db.flush()
    law = Chapter(
        course_id=course.id,
        title="第九章 全面依法治国",
        content="全面依法治国是国家治理的一场深刻革命。深入学习习近平法治思想，推进法治宣传教育，建设社会主义法治文化。",
    )
    military = Chapter(
        course_id=course.id,
        title="第十二章 建设巩固国防和强大人民军队",
        content="坚持党对人民军队的绝对领导，加强军事人才队伍建设，推进国防和军队现代化。",
    )
    economy = Chapter(
        course_id=course.id,
        title="第六章 推动高质量发展",
        content="贯彻新发展理念，加快构建新发展格局，推动经济实现质的有效提升和量的合理增长。",
    )
    db.add_all([law, military, economy]); db.commit()
    return course, law, military, economy


def test_rrf_fuses_rankings_without_comparing_raw_scores() -> None:
    scores = reciprocal_rank_fusion(
        {"bm25": [1, 2, 2, 3], "vector": [2, 1, 4], "lexical": [1, 3]},
        weights={"bm25": 1.0, "vector": 1.0, "lexical": 0.8},
        rank_constant=60,
    )
    normalized = normalize_rrf_scores(
        scores,
        channel_weights=[1.0, 1.0, 0.8],
        rank_constant=60,
    )
    assert max(scores, key=scores.get) == 1
    assert scores[2] > scores[3] > scores[4]
    assert all(0 <= score <= 1 for score in normalized.values())


def test_optional_bge_cross_encoder_adapter_scores_pairs(monkeypatch) -> None:
    fake_module = ModuleType("FlagEmbedding")

    class FakeReranker:
        def __init__(self, model_name, **options):
            assert model_name == "BAAI/bge-reranker-v2-m3"
            assert options["devices"] == ["cpu"]

        def compute_score(self, pairs, *, normalize):
            assert normalize is True
            return [0.82 for _ in pairs]

    fake_module.FlagReranker = FakeReranker
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)
    monkeypatch.setattr(settings, "authority_matching_reranker_enabled", True)
    matcher = OptionalOpenSourceMatcher()

    assert matcher.rerank([("法治宣传教育规划", "全面依法治国")]) == [0.82]


def test_optional_chinese_nli_adapter_maps_model_labels(monkeypatch) -> None:
    transformers_module = ModuleType("transformers")
    torch_module = ModuleType("torch")

    class FakeTensor:
        def __init__(self, value=None):
            self.value = value

        def to(self, _device):
            return self

        def cpu(self):
            return self

        def tolist(self):
            return self.value

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, _model_name):
            return cls()

        def __call__(self, *_args, **_kwargs):
            return {"input_ids": FakeTensor()}

    class FakeModel:
        config = SimpleNamespace(id2label={0: "CONTRADICTION", 1: "NEUTRAL", 2: "ENTAILMENT"})

        @classmethod
        def from_pretrained(cls, _model_name):
            return cls()

        def to(self, _device):
            return self

        def eval(self):
            return self

        def __call__(self, **_kwargs):
            return SimpleNamespace(logits=FakeTensor())

    transformers_module.AutoTokenizer = FakeTokenizer
    transformers_module.AutoModelForSequenceClassification = FakeModel
    torch_module.no_grad = nullcontext
    torch_module.softmax = lambda *_args, **_kwargs: FakeTensor([[0.05, 0.90, 0.05]])
    monkeypatch.setitem(sys.modules, "transformers", transformers_module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)
    monkeypatch.setattr(settings, "authority_matching_nli_enabled", True)
    matcher = OptionalOpenSourceMatcher()

    predictions = matcher.nli([("旧表述", "新表述")])

    assert predictions is not None
    assert predictions[0].label == "neutral"
    assert predictions[0].confidence == 0.90


def test_deterministic_fallback_matches_law_and_allows_no_match(db, monkeypatch) -> None:
    _, law, military, _ = _curriculum(db)
    monkeypatch.setattr(open_source_matcher, "rerank", lambda pairs: None)
    law_candidate = _candidate(
        db,
        title="法治宣传教育第九个五年规划",
        content="全面贯彻习近平法治思想，深入开展法治宣传教育，健全社会主义法治文化建设工作体系。",
    )
    unrelated = _candidate(
        db,
        title="古典音乐演奏会节目单",
        content="本场音乐会演奏小提琴协奏曲和交响曲，观众可按座位编号有序入场。",
    )

    service = AuthorityDiscoveryService(db)
    law_result = service.associate_candidate(law_candidate.id)
    unrelated_result = service.associate_candidate(unrelated.id)

    assert law_result.suggested_chapter_ids
    assert law_result.suggested_chapter_ids[0] == law.id
    assert military.id not in law_result.suggested_chapter_ids
    assert unrelated_result.suggested_chapter_ids == []
    assert unrelated_result.association_confidence == 0
    assert unrelated_result.importance_level == "observe"


def test_low_reranker_scores_can_veto_all_chapters(db, monkeypatch) -> None:
    _curriculum(db)
    candidate = _candidate(
        db,
        title="法治宣传教育规划",
        content="全面贯彻习近平法治思想，推进法治宣传教育。",
    )
    monkeypatch.setattr(open_source_matcher, "rerank", lambda pairs: [0.1] * len(pairs))

    result = AuthorityDiscoveryService(db).associate_candidate(candidate.id)

    assert result.suggested_chapter_ids == []
    assert result.association_confidence == 0


def test_llm_review_cannot_remove_deterministic_web_candidates(db, monkeypatch) -> None:
    _, law, _, _ = _curriculum(db)
    candidate = _candidate(
        db,
        title="法治宣传教育规划",
        content="全面贯彻习近平法治思想，推进法治宣传教育工作体系建设。",
    )
    monkeypatch.setattr(open_source_matcher, "rerank", lambda pairs: None)
    monkeypatch.setattr(
        AuthorityDiscoveryService,
        "_semantic_association_review",
        lambda *_args, **_kwargs: ([], 0.95, "生成模型未选择候选"),
    )

    result = AuthorityDiscoveryService(db).associate_candidate(candidate.id)

    assert result.suggested_chapter_ids
    assert result.suggested_chapter_ids[0] == law.id
    assert result.association_confidence > 0


def test_policy_evidence_is_chapter_scoped_and_never_uses_military_course_fallback(db, monkeypatch) -> None:
    course, law, _, _ = _curriculum(db)
    law_document = KnowledgeDocument(
        source_title="既有法治宣传教育文件",
        source_type="md",
        original_filename="law.md",
        stored_path="/not/existing/law.md",
        course_id=None,
        chapter_id=None,
        vector_collection="test",
        material_type="central",
        publisher="中央机关",
        review_status="published",
        is_active=True,
        status="ready",
        chunk_count=1,
    )
    military_document = KnowledgeDocument(
        source_title="推进国防和军队现代化",
        source_type="md",
        original_filename="military.md",
        stored_path="/not/existing/military.md",
        course_id=None,
        chapter_id=None,
        vector_collection="test",
        material_type="central",
        publisher="中央机关",
        review_status="published",
        is_active=True,
        status="ready",
        chunk_count=1,
    )
    db.add_all([law_document, military_document]); db.flush()
    db.add(DocumentChapterScope(document_id=law_document.id, chapter_id=law.id, confirmed=True))
    db.add(DocumentCourseScope(document_id=military_document.id, course_id=course.id, confirmed=True))
    db.add_all([
        KnowledgeChunk(
            document_id=law_document.id,
            chapter_id=law.id,
            chunk_index=0,
            content="深入学习宣传习近平法治思想，完善法治宣传教育工作体系。",
            vector_id="law-evidence",
            pdf_page_start=1,
            pdf_page_end=1,
            index_version="test-v1",
        ),
        KnowledgeChunk(
            document_id=military_document.id,
            chapter_id=None,
            chunk_index=0,
            content="加强军事人才队伍建设，确保现代化武器装备掌握在革命化人才队伍手中。",
            vector_id="military-evidence",
            pdf_page_start=1,
            pdf_page_end=1,
            index_version="test-v1",
        ),
    ])
    candidate = _candidate(
        db,
        title="法治宣传教育第九个五年规划",
        content="深入贯彻习近平法治思想，健全法治宣传教育工作体系，繁荣发展社会主义法治文化。",
    )
    candidate.suggested_course_ids = [course.id]
    candidate.suggested_chapter_ids = [law.id]
    candidate.association_confidence = 0.9
    db.commit()
    monkeypatch.setattr(open_source_matcher, "rerank", lambda pairs: None)
    monkeypatch.setattr(open_source_matcher, "nli", lambda pairs: None)

    service = AuthorityDiscoveryService(db)
    references = service._reference_sources(candidate)
    changes = service.detect_policy_changes(candidate.id)

    assert any(reference.document_id == law_document.id for reference in references)
    assert all(reference.document_id != military_document.id for reference in references)
    assert changes
    assert all(change.old_source_title != military_document.source_title for change in changes)
    assert all(change.old_chapter_id == law.id for change in changes)
    assert all(0 < change.evidence_confidence <= 1 for change in changes)


def test_nli_neutral_rejects_policy_evidence(db, monkeypatch) -> None:
    course, law, _, _ = _curriculum(db)
    candidate = _candidate(
        db,
        title="全面依法治国新部署",
        content="深入推进全面依法治国，健全法治宣传教育体系。",
    )
    candidate.suggested_course_ids = [course.id]
    candidate.suggested_chapter_ids = [law.id]
    candidate.association_confidence = 0.9
    db.commit()
    monkeypatch.setattr(open_source_matcher, "rerank", lambda pairs: None)
    monkeypatch.setattr(
        open_source_matcher,
        "nli",
        lambda pairs: [
            NliPrediction(label="neutral", confidence=0.9, probabilities={"neutral": 0.9})
            for _ in pairs
        ],
    )

    assert AuthorityDiscoveryService(db).detect_policy_changes(candidate.id) == []


def test_low_chapter_confidence_never_creates_urgent_policy_alert(db, monkeypatch) -> None:
    course, law, _, _ = _curriculum(db)
    candidate = _candidate(
        db,
        title="全面依法治国相关网页",
        content="深入推进全面依法治国，健全法治宣传教育体系。",
    )
    candidate.suggested_course_ids = [course.id]
    candidate.suggested_chapter_ids = [law.id]
    candidate.association_confidence = 0.30
    db.commit()
    monkeypatch.setattr(open_source_matcher, "rerank", lambda pairs: None)
    monkeypatch.setattr(open_source_matcher, "nli", lambda pairs: None)

    changes = AuthorityDiscoveryService(db).detect_policy_changes(candidate.id)

    assert changes
    assert all(change.alert_recommended is False for change in changes)
    assert all(change.importance == "low" for change in changes)


def test_offline_metric_calculation_covers_no_match_and_cross_chapter_errors() -> None:
    metrics = evaluate_matching_cases([
        MatchingEvaluationCase(
            case_id="law",
            expected_chapter_ids={9},
            predicted_chapter_ids=[9],
            evidence=[EvidenceEvaluation(is_correct=True, is_cross_chapter=False)],
        ),
        MatchingEvaluationCase(
            case_id="military",
            expected_chapter_ids={12},
            predicted_chapter_ids=[12, 3],
            evidence=[EvidenceEvaluation(is_correct=True, is_cross_chapter=False)],
        ),
        MatchingEvaluationCase(
            case_id="unrelated",
            expected_chapter_ids=set(),
            predicted_chapter_ids=[],
        ),
    ])

    assert metrics["chapter_precision_at_1"] == 1
    assert metrics["chapter_recall_at_3"] == 1
    assert metrics["evidence_pair_accuracy"] == 1
    assert metrics["cross_chapter_mismatch_rate"] == 0
    assert metrics["no_match_accuracy"] == 1


def test_offline_regression_corpus_meets_quality_gates(db, monkeypatch) -> None:
    _, law, military, _ = _curriculum(db)
    monkeypatch.setattr(open_source_matcher, "rerank", lambda pairs: None)
    monkeypatch.setattr(open_source_matcher, "nli", lambda pairs: None)
    candidates = [
        (
            "law",
            {law.id},
            _candidate(
                db,
                title="法治宣传教育第九个五年规划",
                content="全面贯彻习近平法治思想，健全法治宣传教育体系，繁荣发展社会主义法治文化。",
            ),
        ),
        (
            "military",
            {military.id},
            _candidate(
                db,
                title="高质量推进国防和军队现代化",
                content="坚持党对人民军队的绝对领导，加强军事人才队伍建设，推进国防和军队现代化。",
            ),
        ),
        (
            "unrelated",
            set(),
            _candidate(
                db,
                title="古典音乐演奏会节目单",
                content="本场演奏小提琴协奏曲与交响曲，请观众根据座位编号有序入场。",
            ),
        ),
    ]
    service = AuthorityDiscoveryService(db)
    cases: list[MatchingEvaluationCase] = []
    for case_id, expected, candidate in candidates:
        result = service.associate_candidate(candidate.id)
        evidence: list[EvidenceEvaluation] = []
        if case_id == "law":
            changes = service.detect_policy_changes(candidate.id)
            evidence = [
                EvidenceEvaluation(
                    is_correct=change.old_chapter_id == law.id,
                    is_cross_chapter=change.old_chapter_id not in {None, law.id},
                )
                for change in changes
            ]
        cases.append(MatchingEvaluationCase(
            case_id=case_id,
            expected_chapter_ids=expected,
            predicted_chapter_ids=list(result.suggested_chapter_ids or []),
            evidence=evidence,
        ))

    metrics = evaluate_matching_cases(cases)

    assert metrics["evidence_count"] > 0
    assert metrics["chapter_precision_at_1"] >= 0.90
    assert metrics["chapter_recall_at_3"] >= 0.95
    assert metrics["evidence_pair_accuracy"] >= 0.90
    assert metrics["cross_chapter_mismatch_rate"] < 0.02
    assert metrics["no_match_accuracy"] == 1
