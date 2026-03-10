from datetime import date, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from modules.ad.models import BMAccount, AdAccount, Fanpage, AdDailyStat, BudgetChange
from modules.monitor.service import create_alert
from modules.ad.schemas import (
    BMCreate,
    BMUpdate,
    AdAccountCreate,
    AdAccountUpdate,
    FanpageCreate,
    FanpageUpdate,
    AdDailyStatCreate,
    BudgetChangeCreate,
)

RECENT_STATS_DAYS = 30
CPM_MULTIPLIER = 1000
PERCENT_MULTIPLIER = 100
BUDGET_WARNING_DAYS = 3
BUDGET_INCREASE_MULTIPLIER = 2
BUDGET_SPENDING_LIMIT_DAYS = 30
CENTS_MULTIPLIER = 100
ALERT_BUDGET_OVERSPEND_MULTIPLIER = 1.2
ALERT_CTR_THRESHOLD = 0.5
ALERT_CTR_DAYS = 3

def parse_date(date_value: str) -> date:
    try:
        return date.fromisoformat(date_value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

def calculate_stat_metrics(spend: int, impressions: int, clicks: int, conversions: int):
    cpm = 0
    cpc = 0
    ctr = 0.0
    cvr = 0.0
    if impressions > 0:
        cpm = int(round(spend / impressions * CPM_MULTIPLIER))
        ctr = clicks / impressions * PERCENT_MULTIPLIER
    if clicks > 0:
        cpc = int(round(spend / clicks))
        cvr = conversions / clicks * PERCENT_MULTIPLIER
    return {
        "cpm": cpm,
        "cpc": cpc,
        "ctr": ctr,
        "cvr": cvr,
        "roas": 0.0,
        "cpp": 0,
    }

async def resolve_fb_account_id(db: AsyncSession, ad_account: AdAccount):
    if not ad_account.bm_id:
        return None
    bm = await db.get(BMAccount, ad_account.bm_id)
    if not bm:
        return None
    return bm.fb_account_id

def format_cents(cents: int):
    return f"${cents / CENTS_MULTIPLIER:.2f}"

def parse_spending_limit_to_cents(spending_limit: str):
    if not spending_limit:
        return None
    normalized = spending_limit.strip().lower()
    if normalized == "unlimited":
        return None
    if normalized.startswith("$"):
        normalized = normalized[1:]
    try:
        value = float(normalized)
    except ValueError:
        return None
    return int(round(value * CENTS_MULTIPLIER))

async def get_bm_list(db: AsyncSession, status: str = None):
    stmt = select(BMAccount).options(selectinload(BMAccount.ad_accounts))
    if status:
        stmt = stmt.where(BMAccount.status == status)
    stmt = stmt.order_by(BMAccount.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_bm(db: AsyncSession, data: BMCreate):
    db_bm = BMAccount(
        bm_id=data.bm_id,
        fb_account_id=data.fb_account_id,
        name=data.name,
        region=data.region,
    )
    db.add(db_bm)
    await db.flush()
    return db_bm

async def update_bm(db: AsyncSession, bm_id: int, data: BMUpdate):
    db_bm = await db.get(BMAccount, bm_id)
    if not db_bm:
        return None
    if data.name is not None:
        db_bm.name = data.name
    if data.region is not None:
        db_bm.region = data.region
    if data.status is not None:
        db_bm.status = data.status
    if data.notes is not None:
        db_bm.notes = data.notes
    if data.fb_account_id is not None:
        assert data.fb_account_id > 0
        db_bm.fb_account_id = data.fb_account_id
    db.add(db_bm)
    await db.flush()
    return db_bm

async def delete_bm(db: AsyncSession, bm_id: int):
    db_bm = await db.get(BMAccount, bm_id)
    if not db_bm:
        return None
    stmt = select(func.count(AdAccount.id)).where(AdAccount.bm_id == bm_id)
    result = await db.execute(stmt)
    ad_account_count = result.scalar_one()
    if ad_account_count > 0:
        raise HTTPException(status_code=400, detail="BM has ad accounts")
    await db.delete(db_bm)
    await db.flush()
    return True

async def get_ad_accounts(db: AsyncSession, bm_id: int = None, status: str = None):
    stmt = select(AdAccount).options(selectinload(AdAccount.bm))
    if bm_id is not None:
        stmt = stmt.where(AdAccount.bm_id == bm_id)
    if status:
        stmt = stmt.where(AdAccount.status == status)
    stmt = stmt.order_by(AdAccount.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_ad_account(db: AsyncSession, data: AdAccountCreate):
    db_ad_account = AdAccount(
        ad_account_id=data.ad_account_id,
        bm_id=data.bm_id,
        name=data.name,
        spending_limit=data.spending_limit,
        payment_method=data.payment_method,
    )
    db.add(db_ad_account)
    await db.flush()
    return db_ad_account

async def update_ad_account(db: AsyncSession, ad_account_id: int, data: AdAccountUpdate):
    db_ad_account = await db.get(AdAccount, ad_account_id)
    if not db_ad_account:
        return None
    old_budget = db_ad_account.daily_budget
    old_status = db_ad_account.status
    warnings = []
    if data.name is not None:
        db_ad_account.name = data.name
    if data.spending_limit is not None:
        db_ad_account.spending_limit = data.spending_limit
    if data.payment_method is not None:
        db_ad_account.payment_method = data.payment_method
    if data.status is not None:
        db_ad_account.status = data.status
        if data.status != old_status:
            fb_account_id = await resolve_fb_account_id(db, db_ad_account)
            if data.status == "disabled":
                await create_alert(
                    db,
                    fb_account_id=fb_account_id,
                    level="CRITICAL",
                    title="广告账户被禁用",
                    message=f"广告账户 {db_ad_account.ad_account_id} 已被禁用，请检查违规原因"
                )
            if data.status == "review":
                await create_alert(
                    db,
                    fb_account_id=fb_account_id,
                    level="WARN",
                    title="广告账户审核中",
                    message=f"广告账户 {db_ad_account.ad_account_id} 正在审核，投放已暂停"
                )
    if data.daily_budget is not None and data.daily_budget != old_budget:
        assert data.daily_budget >= 0
        assert old_budget is not None
        budget_reason = data.reason.strip() if data.reason else None
        if not budget_reason:
            budget_reason = f"手动调整 ${old_budget / CENTS_MULTIPLIER:.2f} → ${data.daily_budget / CENTS_MULTIPLIER:.2f}"
        if data.daily_budget > old_budget:
            # PRD 约束：不停止正在投放中的广告
            # PRD 约束：不在同一时间开启第二个广告系列
            # PRD 约束：每次预算递增必须有数据稳定依据
            latest_increase_stmt = select(BudgetChange).where(
                BudgetChange.ad_account_id == ad_account_id,
                BudgetChange.new_budget > BudgetChange.old_budget
            ).order_by(BudgetChange.changed_at.desc())
            latest_increase_result = await db.execute(latest_increase_stmt)
            latest_increase = latest_increase_result.scalars().first()
            if latest_increase:
                delta = datetime.utcnow() - latest_increase.changed_at
                if delta < timedelta(days=BUDGET_WARNING_DAYS):
                    warnings.append("距离上次预算调整不足 3 天，建议等待数据稳定")
            if old_budget > 0 and data.daily_budget >= old_budget * BUDGET_INCREASE_MULTIPLIER:
                warnings.append("预算递增幅度较大（>100%），建议渐进递增")
            spending_limit_cents = parse_spending_limit_to_cents(db_ad_account.spending_limit)
            if spending_limit_cents is not None:
                projected_month_spend = data.daily_budget * BUDGET_SPENDING_LIMIT_DAYS
                if projected_month_spend > spending_limit_cents:
                    warnings.append("预算递增后预计月消耗超过额度层级上限，请确认额度")
        db_ad_account.daily_budget = data.daily_budget
        db.add(BudgetChange(
            ad_account_id=ad_account_id,
            old_budget=old_budget,
            new_budget=data.daily_budget,
            reason=budget_reason
        ))
    if data.notes is not None:
        db_ad_account.notes = data.notes
    db.add(db_ad_account)
    await db.flush()
    return {"data": db_ad_account, "warnings": warnings}

async def get_ad_account_detail(db: AsyncSession, ad_account_id: int):
    stmt = select(AdAccount).where(AdAccount.id == ad_account_id).options(selectinload(AdAccount.bm))
    result = await db.execute(stmt)
    ad_account = result.scalar_one_or_none()
    if not ad_account:
        return None
    end_date = date.today()
    start_date = end_date - timedelta(days=RECENT_STATS_DAYS - 1)
    stats_stmt = select(AdDailyStat).where(
        AdDailyStat.ad_account_id == ad_account_id,
        AdDailyStat.date >= start_date,
        AdDailyStat.date <= end_date,
    ).order_by(AdDailyStat.date.desc())
    stats_result = await db.execute(stats_stmt)
    stats = stats_result.scalars().all()
    changes_stmt = select(BudgetChange).where(
        BudgetChange.ad_account_id == ad_account_id
    ).order_by(BudgetChange.changed_at.desc())
    changes_result = await db.execute(changes_stmt)
    budget_changes = changes_result.scalars().all()
    return {
        "account": ad_account,
        "bm": ad_account.bm,
        "recent_stats": stats,
        "budget_changes": budget_changes,
    }

async def get_fanpages(db: AsyncSession, fb_account_id: int = None):
    stmt = select(Fanpage).options(selectinload(Fanpage.fb_account))
    if fb_account_id is not None:
        stmt = stmt.where(Fanpage.fb_account_id == fb_account_id)
    stmt = stmt.order_by(Fanpage.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_fanpage(db: AsyncSession, data: FanpageCreate):
    db_fanpage = Fanpage(
        page_id=data.page_id,
        fb_account_id=data.fb_account_id,
        page_name=data.page_name,
        page_url=data.page_url,
    )
    db.add(db_fanpage)
    await db.flush()
    return db_fanpage

async def update_fanpage(db: AsyncSession, fanpage_id: int, data: FanpageUpdate):
    db_fanpage = await db.get(Fanpage, fanpage_id)
    if not db_fanpage:
        return None
    if data.page_name is not None:
        db_fanpage.page_name = data.page_name
    if data.page_url is not None:
        db_fanpage.page_url = data.page_url
    if data.status is not None:
        db_fanpage.status = data.status
    if data.pixel_installed is not None:
        db_fanpage.pixel_installed = data.pixel_installed
    if data.domain_verified is not None:
        db_fanpage.domain_verified = data.domain_verified
    db.add(db_fanpage)
    await db.flush()
    return db_fanpage

async def create_or_update_stat(db: AsyncSession, data: AdDailyStatCreate):
    assert data.ad_account_id > 0
    assert data.spend >= 0
    assert data.impressions >= 0
    assert data.clicks >= 0
    assert data.conversions >= 0
    ad_account = await db.get(AdAccount, data.ad_account_id)
    assert ad_account is not None
    fb_account_id = await resolve_fb_account_id(db, ad_account)
    stat_date = parse_date(data.date)
    stmt = select(AdDailyStat).where(
        AdDailyStat.ad_account_id == data.ad_account_id,
        AdDailyStat.date == stat_date,
    )
    result = await db.execute(stmt)
    db_stat = result.scalar_one_or_none()
    metrics = calculate_stat_metrics(data.spend, data.impressions, data.clicks, data.conversions)
    if db_stat:
        db_stat.spend = data.spend
        db_stat.impressions = data.impressions
        db_stat.clicks = data.clicks
        db_stat.conversions = data.conversions
        db_stat.cpm = metrics["cpm"]
        db_stat.cpc = metrics["cpc"]
        db_stat.ctr = metrics["ctr"]
        db_stat.cvr = metrics["cvr"]
        db_stat.roas = metrics["roas"]
        db_stat.cpp = metrics["cpp"]
        db.add(db_stat)
        await db.flush()
        await handle_stat_alerts(db, ad_account, fb_account_id)
        return db_stat
    db_stat = AdDailyStat(
        ad_account_id=data.ad_account_id,
        date=stat_date,
        spend=data.spend,
        impressions=data.impressions,
        clicks=data.clicks,
        conversions=data.conversions,
        cpm=metrics["cpm"],
        cpc=metrics["cpc"],
        ctr=metrics["ctr"],
        cvr=metrics["cvr"],
        roas=metrics["roas"],
        cpp=metrics["cpp"],
    )
    db.add(db_stat)
    await db.flush()
    await handle_stat_alerts(db, ad_account, fb_account_id)
    return db_stat

async def handle_stat_alerts(db: AsyncSession, ad_account: AdAccount, fb_account_id: int | None):
    if ad_account.daily_budget > 0:
        latest_stat_stmt = select(AdDailyStat).where(
            AdDailyStat.ad_account_id == ad_account.id
        ).order_by(AdDailyStat.date.desc()).limit(1)
        latest_stat_result = await db.execute(latest_stat_stmt)
        latest_stat = latest_stat_result.scalar_one_or_none()
        if latest_stat and latest_stat.spend > ad_account.daily_budget * ALERT_BUDGET_OVERSPEND_MULTIPLIER:
            await create_alert(
                db,
                fb_account_id=fb_account_id,
                level="WARN",
                title="消耗超预算",
                message=f"广告账户 {ad_account.ad_account_id} 今日消耗 {format_cents(latest_stat.spend)} 超过日预算 {format_cents(ad_account.daily_budget)} 的 120%"
            )
    ctr_stmt = select(AdDailyStat).where(
        AdDailyStat.ad_account_id == ad_account.id
    ).order_by(AdDailyStat.date.desc()).limit(ALERT_CTR_DAYS)
    ctr_result = await db.execute(ctr_stmt)
    ctr_stats = ctr_result.scalars().all()
    if len(ctr_stats) == ALERT_CTR_DAYS and all(item.ctr < ALERT_CTR_THRESHOLD for item in ctr_stats):
        await create_alert(
            db,
            fb_account_id=fb_account_id,
            level="WARN",
            title="CTR 持续偏低",
            message=f"广告账户 {ad_account.ad_account_id} 连续 3 天 CTR < 0.5%，建议优化素材"
        )

async def get_stats(db: AsyncSession, ad_account_id: int, date_start: str = None, date_end: str = None):
    assert ad_account_id > 0
    stmt = select(AdDailyStat).where(AdDailyStat.ad_account_id == ad_account_id)
    if date_start:
        stmt = stmt.where(AdDailyStat.date >= parse_date(date_start))
    if date_end:
        stmt = stmt.where(AdDailyStat.date <= parse_date(date_end))
    stmt = stmt.order_by(AdDailyStat.date.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

async def get_stats_summary(db: AsyncSession, ad_account_id: int):
    assert ad_account_id > 0
    stmt = select(
        func.sum(AdDailyStat.spend),
        func.sum(AdDailyStat.impressions),
        func.sum(AdDailyStat.clicks),
        func.sum(AdDailyStat.conversions),
    ).where(AdDailyStat.ad_account_id == ad_account_id)
    result = await db.execute(stmt)
    total_spend, total_impressions, total_clicks, total_conversions = result.one()
    total_spend = total_spend or 0
    total_impressions = total_impressions or 0
    total_clicks = total_clicks or 0
    total_conversions = total_conversions or 0
    average_ctr = 0.0
    average_cpc = 0.0
    if total_impressions > 0:
        average_ctr = total_clicks / total_impressions * PERCENT_MULTIPLIER
    if total_clicks > 0:
        average_cpc = total_spend / total_clicks
    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_conversions": total_conversions,
        "average_ctr": average_ctr,
        "average_cpc": average_cpc,
    }

async def get_budget_history(db: AsyncSession, ad_account_id: int):
    assert ad_account_id > 0
    stmt = select(BudgetChange).where(BudgetChange.ad_account_id == ad_account_id).order_by(BudgetChange.changed_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_budget_change(db: AsyncSession, data: BudgetChangeCreate):
    assert data.ad_account_id > 0
    db_change = BudgetChange(
        ad_account_id=data.ad_account_id,
        old_budget=data.old_budget,
        new_budget=data.new_budget,
        reason=data.reason,
    )
    db.add(db_change)
    await db.flush()
    return db_change

async def get_ad_overview(db: AsyncSession):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = date(today.year, today.month, 1)
    trend_start = today - timedelta(days=13)
    today_stmt = select(func.sum(AdDailyStat.spend)).select_from(AdDailyStat).join(
        AdAccount, AdAccount.id == AdDailyStat.ad_account_id
    ).where(
        AdDailyStat.date == today,
        AdAccount.status == "active",
    )
    today_result = await db.execute(today_stmt)
    today_spend = today_result.scalar_one() or 0
    week_stmt = select(func.sum(AdDailyStat.spend)).where(
        AdDailyStat.date >= week_start,
        AdDailyStat.date <= today,
    )
    week_result = await db.execute(week_stmt)
    week_spend = week_result.scalar_one() or 0
    month_stmt = select(func.sum(AdDailyStat.spend)).where(
        AdDailyStat.date >= month_start,
        AdDailyStat.date <= today,
    )
    month_result = await db.execute(month_stmt)
    month_spend = month_result.scalar_one() or 0
    avg_cpp_stmt = select(func.avg(AdDailyStat.cpp)).where(
        AdDailyStat.date >= month_start,
        AdDailyStat.date <= today,
    )
    avg_cpp_result = await db.execute(avg_cpp_stmt)
    avg_cpp_value = avg_cpp_result.scalar_one()
    avg_cpp = int(round(avg_cpp_value)) if avg_cpp_value is not None else 0
    trend_stmt = select(
        AdDailyStat.date,
        func.sum(AdDailyStat.spend),
    ).where(
        AdDailyStat.date >= trend_start,
        AdDailyStat.date <= today,
    ).group_by(
        AdDailyStat.date
    ).order_by(
        AdDailyStat.date.asc()
    )
    trend_result = await db.execute(trend_stmt)
    daily_trend = [
        {"date": stat_date.isoformat(), "spend": int(spend_total or 0)}
        for stat_date, spend_total in trend_result.all()
    ]
    return {
        "today_spend": int(today_spend),
        "week_spend": int(week_spend),
        "month_spend": int(month_spend),
        "avg_cpp": int(avg_cpp),
        "daily_trend": daily_trend,
    }
