from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.authority_discovery import (
    AuthoritySourceCreate, AuthoritySourceRead, AuthoritySourceUpdate,
    CandidateBatchAction, CandidateDecisionSummary, CandidateReview, CandidateTopicGroup, DiscoveryJobCreate,
    DiscoveryJobRead, MaterialCandidateRead, MaterialSnapshotRead, PolicyChangeRead, PolicyChangeReview,
)
from app.schemas.common import ApiResponse
from app.services.authority_discovery_service import (
    AuthorityDiscoveryService, schedule_discovery_job,
)


router = APIRouter(prefix="/knowledge/discovery", tags=["authority-discovery"])
admin_only = require_roles("admin")


@router.get("/sources", response_model=ApiResponse[list[AuthoritySourceRead]])
def list_sources(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> ApiResponse[list[AuthoritySourceRead]]:
    return ApiResponse(data=[AuthoritySourceRead.model_validate(item) for item in AuthorityDiscoveryService(db).list_sources()])


@router.post("/sources", response_model=ApiResponse[AuthoritySourceRead], status_code=status.HTTP_201_CREATED)
def create_source(
    payload: AuthoritySourceCreate,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[AuthoritySourceRead]:
    item = AuthorityDiscoveryService(db).create_source(payload)
    return ApiResponse(message="权威来源已加入白名单", data=AuthoritySourceRead.model_validate(item))


@router.patch("/sources/{source_id}", response_model=ApiResponse[AuthoritySourceRead])
def update_source(
    source_id: int,
    payload: AuthoritySourceUpdate,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[AuthoritySourceRead]:
    item = AuthorityDiscoveryService(db).update_source(source_id, payload)
    return ApiResponse(message="权威来源配置已更新", data=AuthoritySourceRead.model_validate(item))


@router.post("/jobs", response_model=ApiResponse[DiscoveryJobRead], status_code=status.HTTP_202_ACCEPTED)
def create_job(
    payload: DiscoveryJobCreate,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscoveryJobRead]:
    service = AuthorityDiscoveryService(db)
    job = service.create_job(user, payload)
    schedule_discovery_job(job.id, db.get_bind())
    return ApiResponse(message="权威资料发现已转入后台，可离开当前页面", data=DiscoveryJobRead.model_validate(job))


@router.get("/jobs", response_model=ApiResponse[list[DiscoveryJobRead]])
def list_jobs(
    limit: int = Query(default=30, ge=1, le=100),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[list[DiscoveryJobRead]]:
    return ApiResponse(data=[DiscoveryJobRead.model_validate(item) for item in AuthorityDiscoveryService(db).list_jobs(limit)])


@router.get("/jobs/{job_id}", response_model=ApiResponse[DiscoveryJobRead])
def get_job(
    job_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscoveryJobRead]:
    return ApiResponse(data=DiscoveryJobRead.model_validate(AuthorityDiscoveryService(db).require_job(job_id)))


@router.post("/jobs/{job_id}/retry", response_model=ApiResponse[DiscoveryJobRead], status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: int,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscoveryJobRead]:
    service = AuthorityDiscoveryService(db)
    old = service.require_job(job_id)
    if old.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="当前发现任务仍在运行")
    payload = DiscoveryJobCreate(
        query_text=old.query_text, keywords=old.keywords, start_date=old.start_date,
        end_date=old.end_date, source_ids=old.source_ids,
    )
    job = service.create_job(user, payload, trigger_type="retry")
    job.retry_count = old.retry_count + 1
    db.commit()
    db.refresh(job)
    schedule_discovery_job(job.id, db.get_bind())
    return ApiResponse(message="发现任务已重新排队", data=DiscoveryJobRead.model_validate(job))


@router.post("/jobs/{job_id}/cancel", response_model=ApiResponse[DiscoveryJobRead])
def cancel_job(
    job_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscoveryJobRead]:
    job = AuthorityDiscoveryService(db).cancel_job(job_id)
    return ApiResponse(message="发现任务已停止", data=DiscoveryJobRead.model_validate(job))


@router.delete("/jobs/{job_id}", response_model=ApiResponse[dict[str, int]])
def delete_job(
    job_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    deleted_id = AuthorityDiscoveryService(db).delete_job(job_id)
    return ApiResponse(message="发现任务记录已删除", data={"id": deleted_id})


@router.get("/candidates", response_model=ApiResponse[list[MaterialCandidateRead]])
def list_candidates(
    candidate_status: str | None = Query(default=None, alias="status"),
    source_level: str | None = Query(default=None, pattern="^[ABCD]$"),
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[list[MaterialCandidateRead]]:
    service = AuthorityDiscoveryService(db)
    return ApiResponse(data=[MaterialCandidateRead.model_validate(item) for item in service.list_candidates(
        status=candidate_status, source_level=source_level, limit=limit,
    )])


@router.get("/candidates/summary", response_model=ApiResponse[CandidateDecisionSummary])
def candidate_summary(
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[CandidateDecisionSummary]:
    return ApiResponse(data=CandidateDecisionSummary(
        **AuthorityDiscoveryService(db).candidate_decision_summary(),
    ))


@router.get("/candidates/groups", response_model=ApiResponse[list[CandidateTopicGroup]])
def candidate_groups(
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[list[CandidateTopicGroup]]:
    return ApiResponse(data=[
        CandidateTopicGroup(**item)
        for item in AuthorityDiscoveryService(db).candidate_topic_groups()
    ])


@router.post("/candidates/batch", response_model=ApiResponse[dict[str, int]])
def batch_candidates(
    payload: CandidateBatchAction,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    updated = AuthorityDiscoveryService(db).batch_candidates(user, payload)
    return ApiResponse(message="候选材料已批量处理", data={"updated": updated})


@router.get("/candidates/{candidate_id}", response_model=ApiResponse[MaterialCandidateRead])
def get_candidate(
    candidate_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[MaterialCandidateRead]:
    return ApiResponse(data=MaterialCandidateRead.model_validate(AuthorityDiscoveryService(db).require_candidate(candidate_id)))


@router.delete("/candidates/{candidate_id}", response_model=ApiResponse[dict[str, int]])
def delete_candidate(
    candidate_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    deleted_id = AuthorityDiscoveryService(db).delete_candidate(candidate_id)
    return ApiResponse(message="候选材料及其快照、差异证据已删除", data={"id": deleted_id})


@router.get("/candidates/{candidate_id}/snapshots", response_model=ApiResponse[list[MaterialSnapshotRead]])
def list_snapshots(
    candidate_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[list[MaterialSnapshotRead]]:
    service = AuthorityDiscoveryService(db)
    service.require_candidate(candidate_id)
    return ApiResponse(data=[MaterialSnapshotRead.model_validate(item) for item in service.snapshots(candidate_id)])


@router.post("/candidates/{candidate_id}/analyze", response_model=ApiResponse[MaterialCandidateRead])
def analyze_candidate(
    candidate_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[MaterialCandidateRead]:
    item = AuthorityDiscoveryService(db).analyze_candidate(candidate_id)
    return ApiResponse(message="已完成全教材关联与原文差异分析", data=MaterialCandidateRead.model_validate(item))


@router.get("/candidates/{candidate_id}/changes", response_model=ApiResponse[list[PolicyChangeRead]])
def candidate_changes(
    candidate_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[list[PolicyChangeRead]]:
    service = AuthorityDiscoveryService(db)
    service.require_candidate(candidate_id)
    return ApiResponse(data=[PolicyChangeRead.model_validate(item) for item in service.list_changes(candidate_id=candidate_id)])


@router.get("/changes", response_model=ApiResponse[list[PolicyChangeRead]])
def list_policy_changes(
    change_status: str | None = Query(default=None, alias="status"),
    importance: str | None = Query(default=None, pattern="^(high|medium|low)$"),
    candidate_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[list[PolicyChangeRead]]:
    service = AuthorityDiscoveryService(db)
    return ApiResponse(data=[PolicyChangeRead.model_validate(item) for item in service.list_changes(
        status=change_status, importance=importance, candidate_id=candidate_id, limit=limit,
    )])


@router.get("/changes/{change_id}", response_model=ApiResponse[PolicyChangeRead])
def get_policy_change(
    change_id: int,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[PolicyChangeRead]:
    return ApiResponse(data=PolicyChangeRead.model_validate(AuthorityDiscoveryService(db).require_change(change_id)))


@router.post("/changes/{change_id}/review", response_model=ApiResponse[PolicyChangeRead])
def review_policy_change(
    change_id: int,
    payload: PolicyChangeReview,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[PolicyChangeRead]:
    item = AuthorityDiscoveryService(db).review_change(change_id, user, payload.action, payload.note)
    message = {
        "confirm": {
            "synced": "政策变化已确认，知识库已重建并通知相关教师",
            "waiting_publish": "政策变化已确认，待候选材料发布后同步知识库",
            "failed": "政策变化已确认，但知识库重建失败，可稍后重试",
        },
        "dismiss": "政策变化已标记为误判",
        "observe": "政策变化已加入观察",
    }[payload.action]
    if payload.action == "confirm":
        message = message.get(item.kb_sync_status, "政策变化已确认")
    return ApiResponse(message=message, data=PolicyChangeRead.model_validate(item))


@router.post("/changes/{change_id}/sync", response_model=ApiResponse[PolicyChangeRead])
def sync_policy_change(
    change_id: int,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[PolicyChangeRead]:
    item = AuthorityDiscoveryService(db).require_change(change_id)
    if item.review_status != "confirmed":
        raise HTTPException(status_code=409, detail="只有已确认的政策变化可以同步")
    item = AuthorityDiscoveryService(db)._sync_confirmed_change(change_id)
    message = {
        "synced": "知识库索引已重建并完成教师提醒",
        "waiting_publish": "候选材料尚未发布，仍等待进入中央材料",
        "failed": "索引重建失败，请检查原始资料后重试",
    }.get(item.kb_sync_status, "同步状态已更新")
    return ApiResponse(message=message, data=PolicyChangeRead.model_validate(item))


@router.post("/candidates/{candidate_id}/review", response_model=ApiResponse[MaterialCandidateRead])
def review_candidate(
    candidate_id: int,
    payload: CandidateReview,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[MaterialCandidateRead]:
    item = AuthorityDiscoveryService(db).review_candidate(candidate_id, user, payload)
    message = {"publish": "候选材料已进入中央材料并完成发布", "reject": "候选材料已驳回", "duplicate": "候选材料已标记为重复"}[payload.action]
    return ApiResponse(message=message, data=MaterialCandidateRead.model_validate(item))
