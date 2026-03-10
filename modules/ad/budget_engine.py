from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

import yaml
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from db.database import AsyncSessionLocal
from modules.ad.models import AdAccount, AdDailyStat, BudgetChange, BMAccount
from modules.asset.models import FBAccount
from modules.monitor.models import Alert, NurtureTask
from modules.rpa.executor import RPAExecutor

CONFIG_PATH = "config.yaml"
DEFAULT_TIERS = [2, 5, 10, 25, 50, 100]
DEFAULT_MIN_STABLE_DAYS = 3
DEFAULT_MIN_ROAS = 1.0
DEFAULT_MIN_CTR = 0.005
CENTS_MULTIPLIER = 100
ALERT_LEVELS = ["ERROR", "CRITICAL"]

def _load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def _dump_config(config: Dict[str, Any]) -> None:
    content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)

def _normalize_tiers(value: Any) -> List[float]:
    if not isinstance(value, list):
        return DEFAULT_TIERS
    items = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            items.append(number)
    if not items:
        return DEFAULT_TIERS
    return sorted(set(items))

def _normalize_budget_engine_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    config = raw_config if isinstance(raw_config, dict) else {}
    tiers = _normalize_tiers(config.get("tiers"))
    min_stable_days = int(config.get("min_stable_days", DEFAULT_MIN_STABLE_DAYS))
    min_roas = float(config.get("min_roas", DEFAULT_MIN_ROAS))
    min_ctr = float(config.get("min_ctr", DEFAULT_MIN_CTR))
    auto_enabled = bool(config.get("auto_enabled", False))
    check_time = str(config.get("check_time", "10:00"))
    if min_stable_days < 1:
        min_stable_days = DEFAULT_MIN_STABLE_DAYS
    if min_roas < 0:
        min_roas = DEFAULT_MIN_ROAS
    if min_ctr < 0:
        min_ctr = DEFAULT_MIN_CTR
    return {
        "tiers": tiers,
        "min_stable_days": min_stable_days,
        "min_roas": min_roas,
        "min_ctr": min_ctr,
        "auto_enabled": auto_enabled,
        "check_time": check_time,
    }

def read_budget_engine_config() -> Dict[str, Any]:
    config = _load_config()
    raw = config.get("budget_engine", {})
    return _normalize_budget_engine_config(raw)

def save_budget_engine_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    config = _load_config()
    normalized = _normalize_budget_engine_config(payload)
    config["budget_engine"] = normalized
    _dump_config(config)
    return normalized

class BudgetEngine:
    DEFAULT_TIERS = DEFAULT_TIERS
    MIN_STABLE_DAYS = DEFAULT_MIN_STABLE_DAYS

    async def check_upgrade_eligibility(self, ad_account_id: int) -> dict:
        """
        检查广告账户是否满足预算递增条件
        """
        assert ad_account_id > 0
        config = read_budget_engine_config()
        tiers = config["tiers"]
        min_stable_days = config["min_stable_days"]
        min_roas = config["min_roas"]
        min_ctr = config["min_ctr"]

        async with AsyncSessionLocal() as db:
            ad_account = await db.get(AdAccount, ad_account_id)
            if not ad_account:
                return {"eligible": False, "reason": "广告账户不存在", "current_budget": 0.0, "next_budget": 0.0, "metrics": {}}
            if ad_account.status != "active":
                return {"eligible": False, "reason": "广告账户未在投放", "current_budget": ad_account.daily_budget / CENTS_MULTIPLIER, "next_budget": 0.0, "metrics": {}}

            current_budget = float(ad_account.daily_budget or 0) / CENTS_MULTIPLIER
            next_budget = self._next_tier(current_budget, tiers)
            if next_budget is None:
                return {"eligible": False, "reason": "已达最高预算梯度", "current_budget": current_budget, "next_budget": 0.0, "metrics": {}}

            end_date = date.today()
            start_date = end_date - timedelta(days=min_stable_days - 1)
            stats_stmt = select(AdDailyStat).where(
                AdDailyStat.ad_account_id == ad_account_id,
                AdDailyStat.date >= start_date,
                AdDailyStat.date <= end_date
            )
            stats_result = await db.execute(stats_stmt)
            stats = stats_result.scalars().all()
            expected_dates = {start_date + timedelta(days=offset) for offset in range(min_stable_days)}
            stat_dates = {item.date for item in stats}
            if not expected_dates.issubset(stat_dates):
                return {"eligible": False, "reason": "最近数据不完整", "current_budget": current_budget, "next_budget": next_budget, "metrics": {}}

            average_roas = sum(item.roas for item in stats) / len(stats) if stats else 0.0
            average_ctr = sum(item.ctr for item in stats) / len(stats) if stats else 0.0
            ctr_ratio = average_ctr / 100
            if average_roas < min_roas:
                return {"eligible": False, "reason": "ROAS 未达标", "current_budget": current_budget, "next_budget": next_budget, "metrics": {"average_roas": average_roas, "average_ctr": average_ctr}}
            if ctr_ratio < min_ctr:
                return {"eligible": False, "reason": "CTR 未达标", "current_budget": current_budget, "next_budget": next_budget, "metrics": {"average_roas": average_roas, "average_ctr": average_ctr}}

            fb_account_id = None
            if ad_account.bm_id:
                bm = await db.get(BMAccount, ad_account.bm_id)
                if bm:
                    fb_account_id = bm.fb_account_id
            if not fb_account_id:
                return {"eligible": False, "reason": "未绑定 FB 账号", "current_budget": current_budget, "next_budget": next_budget, "metrics": {"average_roas": average_roas, "average_ctr": average_ctr}}

            alert_since = datetime.utcnow() - timedelta(days=min_stable_days)
            alert_stmt = select(func.count(Alert.id)).where(
                Alert.fb_account_id == fb_account_id,
                Alert.level.in_(ALERT_LEVELS),
                Alert.is_dismissed.is_(False),
                Alert.created_at >= alert_since
            )
            alert_result = await db.execute(alert_stmt)
            alert_count = int(alert_result.scalar_one() or 0)
            if alert_count > 0:
                return {"eligible": False, "reason": "存在告警未处理", "current_budget": current_budget, "next_budget": next_budget, "metrics": {"average_roas": average_roas, "average_ctr": average_ctr}}

            latest_increase_stmt = select(BudgetChange).where(
                BudgetChange.ad_account_id == ad_account_id,
                BudgetChange.new_budget > BudgetChange.old_budget
            ).order_by(BudgetChange.changed_at.desc())
            latest_increase_result = await db.execute(latest_increase_stmt)
            latest_increase = latest_increase_result.scalars().first()
            if latest_increase:
                delta_days = (datetime.utcnow() - latest_increase.changed_at).days
                if delta_days < min_stable_days:
                    return {"eligible": False, "reason": "距离上次递增不足稳定天数", "current_budget": current_budget, "next_budget": next_budget, "metrics": {"average_roas": average_roas, "average_ctr": average_ctr}}

            return {
                "eligible": True,
                "reason": "ok",
                "current_budget": current_budget,
                "next_budget": next_budget,
                "metrics": {
                    "average_roas": average_roas,
                    "average_ctr": average_ctr,
                    "stable_days": min_stable_days
                }
            }

    async def auto_upgrade(self, ad_account_id: int) -> dict:
        """
        自动执行预算递增
        """
        assert ad_account_id > 0
        eligibility = await self.check_upgrade_eligibility(ad_account_id)
        if not eligibility.get("eligible"):
            return eligibility

        async with AsyncSessionLocal() as db:
            ad_account = await db.get(AdAccount, ad_account_id)
            if not ad_account:
                return {"eligible": False, "reason": "广告账户不存在", "current_budget": 0.0, "next_budget": 0.0, "metrics": {}}
            bm = await db.get(BMAccount, ad_account.bm_id) if ad_account.bm_id else None
            fb_account_id = bm.fb_account_id if bm else None
            if not fb_account_id:
                return {"eligible": False, "reason": "未绑定 FB 账号", "current_budget": eligibility["current_budget"], "next_budget": eligibility["next_budget"], "metrics": eligibility.get("metrics", {})}

            stmt_account = select(FBAccount).where(FBAccount.id == fb_account_id).options(
                selectinload(FBAccount.browser_window),
                selectinload(FBAccount.proxy)
            )
            result_account = await db.execute(stmt_account)
            fb_account = result_account.scalar_one_or_none()
            if not fb_account:
                return {"eligible": False, "reason": "FB 账号不存在", "current_budget": eligibility["current_budget"], "next_budget": eligibility["next_budget"], "metrics": eligibility.get("metrics", {})}

            average_roas = float(eligibility["metrics"].get("average_roas", 0))
            average_ctr = float(eligibility["metrics"].get("average_ctr", 0))
            stable_days = int(eligibility["metrics"].get("stable_days", DEFAULT_MIN_STABLE_DAYS))
            reason = f"ROAS {stable_days}日均值 {average_roas:.2f}, CTR {average_ctr:.2f}%, 数据稳定 {stable_days} 天"
            campaign_name = ad_account.name or ad_account.ad_account_id or f"AdAccount-{ad_account.id}"
            task = NurtureTask(
                fb_account_id=fb_account_id,
                day_number=fb_account.nurture_day or 0,
                scheduled_date=date.today(),
                scheduled_time=datetime.now(),
                action="adjust_budget",
                task_type="manual",
                execution_type="auto",
                status="running",
                result_log=None,
                retry_count=0
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)

        executor = RPAExecutor()
        actions = [{
            "action": "rpa.adjust_budget",
            "params": {
                "campaign_name": campaign_name,
                "new_budget": eligibility["next_budget"],
                "budget_reason": reason
            }
        }]
        try:
            await executor.enqueue_task(fb_account, task, actions)
        except Exception as e:
            logger.error(f"预算递增任务执行失败: {e}")
            async with AsyncSessionLocal() as db:
                db_task = await db.get(NurtureTask, task.id)
                if db_task:
                    db_task.status = "failed"
                    db_task.result_log = str(e)
                    db_task.retry_count += 1
                    db.add(db_task)
                    await db.commit()
            return {"eligible": False, "reason": "递增执行失败", "current_budget": eligibility["current_budget"], "next_budget": eligibility["next_budget"], "metrics": eligibility.get("metrics", {})}

        return {
            "eligible": True,
            "reason": reason,
            "current_budget": eligibility["current_budget"],
            "next_budget": eligibility["next_budget"],
            "metrics": eligibility.get("metrics", {}),
            "task_id": task.id
        }

    async def check_all_accounts(self):
        """
        遍历所有投放中的广告账户，检查并执行自动递增
        """
        async with AsyncSessionLocal() as db:
            stmt = select(AdAccount).where(AdAccount.status == "active")
            result = await db.execute(stmt)
            accounts = result.scalars().all()
        results = []
        for account in accounts:
            eligibility = await self.check_upgrade_eligibility(account.id)
            if eligibility.get("eligible"):
                result = await self.auto_upgrade(account.id)
                results.append(result)
            else:
                results.append(eligibility)
        return results

    def _next_tier(self, current_budget: float, tiers: List[float]) -> float | None:
        assert tiers
        sorted_tiers = sorted(set(tiers))
        for tier in sorted_tiers:
            if tier > current_budget + 1e-6:
                return float(tier)
        return None
