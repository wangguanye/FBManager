import asyncio
import os
import random
from datetime import datetime

from sqlalchemy import select

from db.database import AsyncSessionLocal
from modules.ad.models import AdAccount, BMAccount, BudgetChange
from modules.rpa.base import BaseAction, register_action

META = {
    "action_id": "adjust_budget",
    "name": "调整广告预算",
    "params_schema": {
        "campaign_name": {"type": "string", "label": "广告系列名称"},
        "new_budget": {"type": "number", "label": "新日预算(USD)"},
        "budget_reason": {"type": "string", "label": "递增依据"}
    }
}

ADS_MANAGER_URL = "https://www.facebook.com/adsmanager/manage/campaigns"
SCREENSHOT_DIR = "assets/screenshots"
MIN_DELAY_SECONDS = 2
MAX_DELAY_SECONDS = 5
NAV_TIMEOUT_MS = 60000
CENT_MULTIPLIER = 100

SEARCH_SELECTORS = [
    'input[aria-label="Search"]',
    'input[placeholder="Search"]',
    'input[aria-label="搜索"]',
    'input[placeholder="搜索"]'
]

EDIT_SELECTORS = [
    'text="Edit"',
    'text="编辑"'
]

BUDGET_SELECTORS = [
    'input[aria-label="Daily budget"]',
    'input[placeholder="Daily budget"]',
    'input[aria-label="日预算"]',
    'input[placeholder="日预算"]'
]

SAVE_SELECTORS = [
    'text="Publish"',
    'text="Review and publish"',
    'text="Save"',
    'text="保存"',
    'text="发布"'
]

@register_action
class AdjustBudgetAction(BaseAction):
    action_id = "rpa.adjust_budget"

    async def execute(self, page, params, logger) -> dict:
        campaign_name = str(params.get("campaign_name") or "").strip()
        new_budget = float(params.get("new_budget") or 0)
        account_id = int(params.get("account_id") or 0)
        budget_reason = str(params.get("budget_reason") or "").strip()
        assert new_budget >= 0

        if not campaign_name:
            return {"success": False, "message": "missing_campaign_name"}
        if new_budget <= 0:
            return {"success": False, "message": "invalid_budget"}
        if account_id <= 0:
            return {"success": False, "message": "missing_account_id"}

        try:
            await page.goto(ADS_MANAGER_URL, timeout=NAV_TIMEOUT_MS)
            await self._step_delay()

            if not await self._fill_first(page, SEARCH_SELECTORS, campaign_name):
                return await self._fail_step(page, logger, "search_campaign")
            await page.keyboard.press("Enter")
            await self._step_delay()

            if not await self._click_campaign(page, campaign_name):
                return await self._fail_step(page, logger, "select_campaign")
            await self._step_delay()

            if not await self._click_first(page, EDIT_SELECTORS):
                return await self._fail_step(page, logger, "edit_campaign")
            await self._step_delay()

            if not await self._fill_first(page, BUDGET_SELECTORS, str(new_budget)):
                return await self._fail_step(page, logger, "update_budget")
            await self._step_delay()

            if not await self._click_first(page, SAVE_SELECTORS):
                return await self._fail_step(page, logger, "save_budget")
            await self._step_delay()

            updated = await self._record_budget_change(account_id, campaign_name, new_budget, budget_reason, logger)
            if not updated:
                return {"success": False, "message": "budget_change_record_failed"}

            return {"success": True, "message": "budget_updated", "data": {"campaign_name": campaign_name}}
        except Exception as e:
            logger.error(f"调整预算异常: {e}")
            await self._capture_screenshot(page, "adjust_budget_exception")
            return {"success": False, "message": str(e)}

    async def _step_delay(self) -> None:
        await asyncio.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))

    async def _click_first(self, page, selectors: list[str]) -> bool:
        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                await element.click()
                return True
        return False

    async def _fill_first(self, page, selectors: list[str], value: str) -> bool:
        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                await element.fill(value)
                return True
        return False

    async def _click_campaign(self, page, campaign_name: str) -> bool:
        element = await page.query_selector(f'text="{campaign_name}"')
        if element:
            await element.click()
            return True
        return False

    async def _record_budget_change(self, account_id: int, campaign_name: str, new_budget: float, budget_reason: str, logger) -> bool:
        async with AsyncSessionLocal() as db:
            stmt = select(AdAccount).join(BMAccount, AdAccount.bm_id == BMAccount.id).where(
                BMAccount.fb_account_id == account_id
            )
            result = await db.execute(stmt)
            ad_accounts = result.scalars().all()
            target = None
            keyword = campaign_name.lower()
            for ad_account in ad_accounts:
                if ad_account.name and keyword in ad_account.name.lower():
                    target = ad_account
                    break
                if ad_account.ad_account_id and keyword == str(ad_account.ad_account_id).lower():
                    target = ad_account
                    break
            if not target and ad_accounts:
                target = ad_accounts[0]
            if not target:
                logger.error("未找到可写入预算记录的广告账户")
                return False

            new_budget_cents = int(round(new_budget * CENT_MULTIPLIER))
            old_budget = int(target.daily_budget or 0)
            target.daily_budget = new_budget_cents
            db.add(target)
            reason = budget_reason or "RPA 调整预算"
            db.add(BudgetChange(
                ad_account_id=target.id,
                old_budget=old_budget,
                new_budget=new_budget_cents,
                reason=reason
            ))
            await db.commit()
            return True

    async def _capture_screenshot(self, page, step: str) -> str:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        filename = f"{SCREENSHOT_DIR}/{step}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.png"
        await page.screenshot(path=filename, full_page=True)
        return filename

    async def _fail_step(self, page, logger, step: str) -> dict:
        screenshot = await self._capture_screenshot(page, step)
        logger.error(f"调整预算失败: {step}")
        return {"success": False, "message": f"{step}_not_found", "data": {"screenshot": screenshot}}
