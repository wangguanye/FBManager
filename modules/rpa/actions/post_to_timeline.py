"""主页发帖动作
参数：content(str), image_url(str, optional), max_per_day(int, default=3)
"""
import asyncio
import os
import random
from datetime import datetime, date, time

from sqlalchemy import select, func

from modules.rpa.base import BaseAction, register_action
from db.database import AsyncSessionLocal
from modules.monitor.models import ActionLog

@register_action
class PostToTimelineAction(BaseAction):
    action_id = "rpa.post_to_timeline"

    async def execute(self, page, params, logger) -> dict:
        content = params.get("content", "")
        image_url = params.get("image_url")
        max_per_day = params.get("max_per_day", 3)

        if not content:
            return {"success": False, "message": "empty_content", "data": {"posted": False, "post_url": None}}

        if self._has_prohibited_content(content):
            return {"success": False, "message": "prohibited_content", "data": {"posted": False, "post_url": None}}

        today_start = datetime.combine(date.today(), time.min)
        async with AsyncSessionLocal() as db:
            stmt = select(func.count(ActionLog.id)).where(
                ActionLog.action_type == self.action_id,
                ActionLog.created_at >= today_start
            )
            result = await db.execute(stmt)
            today_count = result.scalar() or 0

        if today_count >= max_per_day:
            return {"success": True, "message": "daily_limit_reached", "data": {"posted": False, "post_url": None}}

        try:
            await page.goto("https://www.facebook.com/profile", timeout=60000)
            await asyncio.sleep(random.uniform(2, 8))

            post_box = await page.query_selector('div[aria-label="Create a post"], div[aria-label="发帖"], div[role="textbox"]')
            if not post_box:
                return {"success": False, "message": "post_box_not_found", "data": {"posted": False, "post_url": None}}

            await post_box.click()
            await asyncio.sleep(random.uniform(2, 8))

            input_box = await page.query_selector('div[role="textbox"]')
            if not input_box:
                return {"success": False, "message": "input_not_found", "data": {"posted": False, "post_url": None}}

            for ch in content:
                await input_box.type(ch)
                await asyncio.sleep(random.uniform(0.05, 0.15))

            if image_url:
                file_input = await page.query_selector('input[type="file"]')
                if file_input and os.path.exists(image_url):
                    await file_input.set_input_files(image_url)
                    await asyncio.sleep(random.uniform(2, 8))

            publish_button = await page.query_selector('div[aria-label="Post"], div[aria-label="发布"]')
            if not publish_button:
                return {"success": False, "message": "publish_not_found", "data": {"posted": False, "post_url": None}}

            await publish_button.click()
            await asyncio.sleep(random.uniform(2, 8))

        except Exception as e:
            logger.warning(f"主页发帖异常: {e}")
            return {"success": False, "message": str(e), "data": {"posted": False, "post_url": None}}

        return {"success": True, "message": "Post created", "data": {"posted": True, "post_url": None}}

    def _has_prohibited_content(self, content: str) -> bool:
        lower_content = content.lower()
        if "http://" in lower_content or "https://" in lower_content or "www." in lower_content:
            return True
        ad_keywords = ["buy", "sale", "discount", "promo", "offer", "优惠", "折扣", "促销", "购买", "免费"]
        return any(keyword in lower_content for keyword in ad_keywords)
