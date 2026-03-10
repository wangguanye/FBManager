import json
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from modules.health.models import HealthScore
from modules.asset.models import FBAccount
from modules.monitor.models import NurtureTask, ActionLog

WEIGHT_NURTURE_PROGRESS = 0.25
WEIGHT_TASK_COMPLETION = 0.25
WEIGHT_ERROR_FREQUENCY = 0.20
WEIGHT_LOGIN_STABILITY = 0.15
WEIGHT_ASSET_COMPLETENESS = 0.15

NURTURE_FULL_DAYS = 14
TASK_COMPLETION_FULL = 1.0
TASK_COMPLETION_ZERO = 0.5
ERROR_COUNT_ZERO = 5
LOGIN_DAYS_WINDOW = 7
LOGIN_FAIL_CONSECUTIVE_ZERO = 2
ASSET_BASE_SCORE = 60
ASSET_BM_SCORE = 20
ASSET_FANPAGE_SCORE = 20
SCORE_MIN = 0
SCORE_MAX = 100

def clamp_score(value: float) -> int:
    value = max(SCORE_MIN, min(SCORE_MAX, value))
    return int(round(value))

def calculate_grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"

async def calculate_health_score(db: AsyncSession, account: FBAccount) -> Dict[str, Any]:
    assert db is not None
    assert account is not None

    nurture_day = account.nurture_day or 0
    if nurture_day <= 0:
        nurture_score = 0
    elif nurture_day >= NURTURE_FULL_DAYS:
        nurture_score = SCORE_MAX
    else:
        nurture_score = clamp_score(nurture_day / NURTURE_FULL_DAYS * SCORE_MAX)

    date_threshold = date.today() - timedelta(days=LOGIN_DAYS_WINDOW)
    total_stmt = select(func.count(NurtureTask.id)).where(
        NurtureTask.fb_account_id == account.id,
        NurtureTask.scheduled_date >= date_threshold
    )
    completed_stmt = select(func.count(NurtureTask.id)).where(
        NurtureTask.fb_account_id == account.id,
        NurtureTask.status == "completed",
        NurtureTask.scheduled_date >= date_threshold
    )
    total_result = await db.execute(total_stmt)
    completed_result = await db.execute(completed_stmt)
    total_tasks = total_result.scalar() or 0
    completed_tasks = completed_result.scalar() or 0
    if total_tasks <= 0:
        task_completion_score = 0
    else:
        completion_rate = completed_tasks / total_tasks
        if completion_rate >= TASK_COMPLETION_FULL:
            task_completion_score = SCORE_MAX
        elif completion_rate < TASK_COMPLETION_ZERO:
            task_completion_score = 0
        else:
            task_completion_score = clamp_score((completion_rate - TASK_COMPLETION_ZERO) / (TASK_COMPLETION_FULL - TASK_COMPLETION_ZERO) * SCORE_MAX)

    error_threshold = datetime.utcnow() - timedelta(days=LOGIN_DAYS_WINDOW)
    error_stmt = select(func.count(ActionLog.id)).where(
        ActionLog.fb_account_id == account.id,
        ActionLog.level.in_(["ERROR", "CRITICAL"]),
        ActionLog.created_at >= error_threshold
    )
    error_result = await db.execute(error_stmt)
    error_count = error_result.scalar() or 0
    if error_count <= 0:
        error_score = SCORE_MAX
    elif error_count >= ERROR_COUNT_ZERO:
        error_score = 0
    else:
        error_score = clamp_score((ERROR_COUNT_ZERO - error_count) / ERROR_COUNT_ZERO * SCORE_MAX)

    login_threshold = datetime.utcnow() - timedelta(days=LOGIN_DAYS_WINDOW)
    login_stmt = select(func.date(ActionLog.created_at)).where(
        ActionLog.fb_account_id == account.id,
        ActionLog.action_type.ilike("%login%"),
        ActionLog.level == "INFO",
        ActionLog.created_at >= login_threshold
    ).distinct()
    login_result = await db.execute(login_stmt)
    login_days = {str(row[0]) for row in login_result.all() if row[0]}
    today = date.today()
    day_list = [today - timedelta(days=offset) for offset in range(LOGIN_DAYS_WINDOW - 1, -1, -1)]
    success_days = 0
    consecutive_missing = 0
    max_consecutive_missing = 0
    for day in day_list:
        day_key = day.isoformat()
        if day_key in login_days:
            success_days += 1
            consecutive_missing = 0
        else:
            consecutive_missing += 1
            max_consecutive_missing = max(max_consecutive_missing, consecutive_missing)
    if max_consecutive_missing >= LOGIN_FAIL_CONSECUTIVE_ZERO:
        login_score = 0
    else:
        login_score = clamp_score(success_days / LOGIN_DAYS_WINDOW * SCORE_MAX)

    has_proxy = account.proxy_id is not None
    has_window = account.browser_window_id is not None
    has_bm = account.bm_account is not None
    has_fanpage = bool(account.fanpages)
    if not has_proxy or not has_window:
        asset_score = 0
    else:
        asset_score = ASSET_BASE_SCORE
        if has_bm:
            asset_score += ASSET_BM_SCORE
        if has_fanpage:
            asset_score += ASSET_FANPAGE_SCORE
        asset_score = clamp_score(asset_score)

    detail = {
        "nurture_progress": nurture_score,
        "task_completion": task_completion_score,
        "error_frequency": error_score,
        "login_stability": login_score,
        "asset_completeness": asset_score
    }
    score = clamp_score(
        nurture_score * WEIGHT_NURTURE_PROGRESS +
        task_completion_score * WEIGHT_TASK_COMPLETION +
        error_score * WEIGHT_ERROR_FREQUENCY +
        login_score * WEIGHT_LOGIN_STABILITY +
        asset_score * WEIGHT_ASSET_COMPLETENESS
    )
    grade = calculate_grade(score)
    return {
        "score": score,
        "grade": grade,
        "detail_json": detail,
        "calculated_at": datetime.utcnow()
    }

def serialize_health_score(item: HealthScore) -> Dict[str, Any]:
    detail_payload: Optional[Dict[str, Any]] = None
    if item.detail_json:
        try:
            detail_payload = json.loads(item.detail_json)
        except Exception:
            detail_payload = None
    return {
        "id": item.id,
        "fb_account_id": item.fb_account_id,
        "score": item.score,
        "grade": item.grade,
        "detail_json": detail_payload,
        "calculated_at": item.calculated_at
    }

async def get_health_scores(db: AsyncSession, grade: Optional[str] = None, sort: str = "score_desc") -> List[Dict[str, Any]]:
    assert db is not None
    query = select(HealthScore)
    if grade:
        query = query.where(HealthScore.grade == grade)
    if sort == "score_asc":
        query = query.order_by(HealthScore.score.asc())
    else:
        query = query.order_by(HealthScore.score.desc())
    result = await db.execute(query)
    items = result.scalars().all()
    return [serialize_health_score(item) for item in items]

async def get_health_overview(db: AsyncSession) -> Dict[str, Any]:
    assert db is not None
    avg_stmt = select(func.avg(HealthScore.score), func.count(HealthScore.id))
    avg_result = await db.execute(avg_stmt)
    avg_score, total = avg_result.one()
    average_score = int(round(avg_score or 0))
    grade_stmt = select(HealthScore.grade, func.count(HealthScore.id)).group_by(HealthScore.grade)
    grade_result = await db.execute(grade_stmt)
    grade_counts = {row[0]: row[1] for row in grade_result.all() if row[0]}
    return {"average_score": average_score, "total": int(total or 0), "grade_counts": grade_counts}

async def get_health_score_detail(db: AsyncSession, account_id: int) -> Optional[Dict[str, Any]]:
    assert db is not None
    assert account_id is not None
    stmt = select(HealthScore).where(HealthScore.fb_account_id == account_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        return None
    return serialize_health_score(item)

async def recalculate_account_health_score(db: AsyncSession, account_id: int) -> Optional[Dict[str, Any]]:
    assert db is not None
    assert account_id is not None
    stmt = select(FBAccount).where(FBAccount.id == account_id).options(
        selectinload(FBAccount.bm_account),
        selectinload(FBAccount.fanpages)
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if not account:
        return None
    score_payload = await calculate_health_score(db, account)
    detail_text = json.dumps(score_payload["detail_json"], ensure_ascii=False)
    stmt_score = select(HealthScore).where(HealthScore.fb_account_id == account_id)
    existing_result = await db.execute(stmt_score)
    existing = existing_result.scalar_one_or_none()
    if existing:
        existing.score = score_payload["score"]
        existing.grade = score_payload["grade"]
        existing.detail_json = detail_text
        existing.calculated_at = score_payload["calculated_at"]
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        return serialize_health_score(existing)
    new_score = HealthScore(
        fb_account_id=account_id,
        score=score_payload["score"],
        grade=score_payload["grade"],
        detail_json=detail_text,
        calculated_at=score_payload["calculated_at"]
    )
    db.add(new_score)
    await db.commit()
    await db.refresh(new_score)
    return serialize_health_score(new_score)

async def recalculate_all_health_scores(db: AsyncSession) -> List[Dict[str, Any]]:
    assert db is not None
    stmt = select(FBAccount).where(FBAccount.status != "已封禁").options(
        selectinload(FBAccount.bm_account),
        selectinload(FBAccount.fanpages)
    )
    result = await db.execute(stmt)
    accounts = result.scalars().all()
    results = []
    for account in accounts:
        score_payload = await calculate_health_score(db, account)
        detail_text = json.dumps(score_payload["detail_json"], ensure_ascii=False)
        stmt_score = select(HealthScore).where(HealthScore.fb_account_id == account.id)
        existing_result = await db.execute(stmt_score)
        existing = existing_result.scalar_one_or_none()
        if existing:
            existing.score = score_payload["score"]
            existing.grade = score_payload["grade"]
            existing.detail_json = detail_text
            existing.calculated_at = score_payload["calculated_at"]
            db.add(existing)
            results.append(serialize_health_score(existing))
            continue
        new_score = HealthScore(
            fb_account_id=account.id,
            score=score_payload["score"],
            grade=score_payload["grade"],
            detail_json=detail_text,
            calculated_at=score_payload["calculated_at"]
        )
        db.add(new_score)
        await db.flush()
        results.append(serialize_health_score(new_score))
    await db.commit()
    return results
