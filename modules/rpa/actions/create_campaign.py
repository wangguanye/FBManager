import asyncio
import os
import random
from datetime import datetime

from modules.rpa.base import BaseAction, register_action

META = {
    "action_id": "create_campaign",
    "name": "创建广告系列",
    "params_schema": {
        "campaign_name": {"type": "string", "label": "广告系列名称", "default": ""},
        "objective": {"type": "select", "label": "投放目标", "options": ["messages", "traffic", "engagement", "leads"], "default": "messages"},
        "daily_budget": {"type": "number", "label": "日预算(USD)", "default": 2},
        "target_country": {"type": "string", "label": "目标国家", "default": "US"},
        "target_age_min": {"type": "number", "label": "最小年龄", "default": 25},
        "target_age_max": {"type": "number", "label": "最大年龄", "default": 55},
        "target_gender": {"type": "select", "label": "性别", "options": ["all", "female", "male"], "default": "female"},
        "interests": {"type": "string", "label": "兴趣关键词(逗号分隔)", "default": "weight loss,fitness,diet"}
    }
}

ADS_MANAGER_URL = "https://www.facebook.com/adsmanager/manage/campaigns"
SCREENSHOT_DIR = "assets/screenshots"
MIN_DELAY_SECONDS = 2
MAX_DELAY_SECONDS = 5
NAV_TIMEOUT_MS = 60000

OBJECTIVE_SELECTORS = {
    "messages": ['text="Messages"', 'text="Message"', 'text="Messaging"', 'text="消息"', 'text="留言"'],
    "traffic": ['text="Traffic"', 'text="流量"'],
    "engagement": ['text="Engagement"', 'text="互动"', 'text="参与度"'],
    "leads": ['text="Leads"', 'text="潜在客户"', 'text="表单"']
}

GENDER_SELECTORS = {
    "all": ['text="All"', 'text="全部"', 'text="所有"'],
    "female": ['text="Female"', 'text="女性"', 'text="女"'],
    "male": ['text="Male"', 'text="男性"', 'text="男"']
}

CREATE_BUTTON_SELECTORS = [
    'text="+ Create"',
    'text="Create"',
    'text="创建"',
    'div[aria-label="Create"]',
    'div[aria-label="创建"]'
]

CONTINUE_BUTTON_SELECTORS = [
    'text="Continue"',
    'text="Next"',
    'text="继续"',
    'text="下一步"'
]

CAMPAIGN_NAME_SELECTORS = [
    'input[aria-label="Campaign name"]',
    'input[placeholder="Campaign name"]',
    'input[aria-label="广告系列名称"]',
    'input[placeholder="广告系列名称"]'
]

DAILY_BUDGET_SELECTORS = [
    'input[aria-label="Daily budget"]',
    'input[placeholder="Daily budget"]',
    'input[aria-label="日预算"]',
    'input[placeholder="日预算"]'
]

COUNTRY_SELECTORS = [
    'input[aria-label="Add locations"]',
    'input[placeholder="Add locations"]',
    'input[aria-label="Locations"]',
    'input[aria-label="国家"]'
]

AGE_MIN_SELECTORS = [
    'input[aria-label="Age Min"]',
    'input[placeholder="Min age"]',
    'input[aria-label="最小年龄"]'
]

AGE_MAX_SELECTORS = [
    'input[aria-label="Age Max"]',
    'input[placeholder="Max age"]',
    'input[aria-label="最大年龄"]'
]

INTEREST_SELECTORS = [
    'input[aria-label="Interests"]',
    'input[placeholder="Add interests"]',
    'input[aria-label="兴趣"]',
    'input[placeholder="添加兴趣"]'
]

PLACEMENT_SELECTORS = [
    'text="Advantage+ placements"',
    'text="Automatic placements"',
    'text="自动版位"',
    'text="自动放置"'
]

SAVE_DRAFT_SELECTORS = [
    'text="Save Draft"',
    'text="Save draft"',
    'text="保存草稿"',
    'text="Close"',
    'text="关闭"'
]

@register_action
class CreateCampaignAction(BaseAction):
    action_id = "rpa.create_campaign"

    async def execute(self, page, params, logger) -> dict:
        campaign_name = str(params.get("campaign_name") or "").strip()
        objective = params.get("objective") or "messages"
        daily_budget = float(params.get("daily_budget") or 0)
        target_country = str(params.get("target_country") or "US").strip()
        target_age_min = int(params.get("target_age_min") or 0)
        target_age_max = int(params.get("target_age_max") or 0)
        target_gender = params.get("target_gender") or "female"
        interests = str(params.get("interests") or "").strip()
        assert objective in OBJECTIVE_SELECTORS
        assert target_gender in GENDER_SELECTORS

        if not campaign_name:
            return {"success": False, "message": "missing_campaign_name"}

        try:
            await page.goto(ADS_MANAGER_URL, timeout=NAV_TIMEOUT_MS)
            await self._step_delay()

            if not await self._click_first(page, CREATE_BUTTON_SELECTORS):
                return await self._fail_step(page, logger, "create_button")
            await self._step_delay()

            if not await self._click_first(page, OBJECTIVE_SELECTORS[objective]):
                return await self._fail_step(page, logger, "objective")
            await self._step_delay()

            await self._click_first(page, CONTINUE_BUTTON_SELECTORS)
            await self._step_delay()

            if not await self._fill_first(page, CAMPAIGN_NAME_SELECTORS, campaign_name):
                return await self._fail_step(page, logger, "campaign_name")
            await self._step_delay()

            if not await self._fill_first(page, DAILY_BUDGET_SELECTORS, str(daily_budget)):
                return await self._fail_step(page, logger, "daily_budget")
            await self._step_delay()

            if target_country:
                if not await self._fill_first(page, COUNTRY_SELECTORS, target_country):
                    return await self._fail_step(page, logger, "target_country")
                await page.keyboard.press("Enter")
            await self._step_delay()

            if target_age_min > 0:
                if not await self._fill_first(page, AGE_MIN_SELECTORS, str(target_age_min)):
                    return await self._fail_step(page, logger, "target_age_min")
            await self._step_delay()

            if target_age_max > 0:
                if not await self._fill_first(page, AGE_MAX_SELECTORS, str(target_age_max)):
                    return await self._fail_step(page, logger, "target_age_max")
            await self._step_delay()

            if not await self._click_first(page, GENDER_SELECTORS[target_gender]):
                return await self._fail_step(page, logger, "target_gender")
            await self._step_delay()

            if interests:
                if not await self._fill_interests(page, interests):
                    return await self._fail_step(page, logger, "interests")
            await self._step_delay()

            if not await self._click_first(page, PLACEMENT_SELECTORS):
                return await self._fail_step(page, logger, "placements")
            await self._step_delay()

            if not await self._click_first(page, SAVE_DRAFT_SELECTORS):
                return await self._fail_step(page, logger, "save_draft")
            await self._step_delay()

            return {"success": True, "message": "campaign_created", "data": {"campaign_name": campaign_name}}
        except Exception as e:
            logger.error(f"创建广告系列异常: {e}")
            await self._capture_screenshot(page, "create_campaign_exception")
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

    async def _fill_interests(self, page, interests: str) -> bool:
        interest_items = [item.strip() for item in interests.split(",") if item.strip()]
        if not interest_items:
            return True
        input_box = None
        for selector in INTEREST_SELECTORS:
            candidate = await page.query_selector(selector)
            if candidate:
                input_box = candidate
                break
        if not input_box:
            return False
        for keyword in interest_items:
            await input_box.fill(keyword)
            await page.keyboard.press("Enter")
            await self._step_delay()
        return True

    async def _capture_screenshot(self, page, step: str) -> str:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        filename = f"{SCREENSHOT_DIR}/{step}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.png"
        await page.screenshot(path=filename, full_page=True)
        return filename

    async def _fail_step(self, page, logger, step: str) -> dict:
        screenshot = await self._capture_screenshot(page, step)
        logger.error(f"创建广告系列失败: {step}")
        return {"success": False, "message": f"{step}_not_found", "data": {"screenshot": screenshot}}
