"""加入群组动作
参数：group_url(str, optional), max_count(int, default=1)
"""
import asyncio
import random
import time

from modules.rpa.base import BaseAction, register_action

META = {
    "action_id": "join_group",
    "name": "加入群组",
    "params_schema": {
        "group_url": {"type": "string", "label": "群组链接", "default": ""},
        "max_count": {"type": "number", "label": "最大数量", "default": 1}
    }
}

@register_action
class JoinGroupAction(BaseAction):
    action_id = "rpa.join_group"

    async def execute(self, page, params, logger) -> dict:
        group_url = params.get("group_url")
        max_count = params.get("max_count", 1)
        joined_count = 0
        group_names = []

        try:
            if group_url:
                await page.goto(group_url, timeout=60000)
                await asyncio.sleep(random.uniform(2, 8))
                joined = await self._join_current_group(page, logger)
                if joined:
                    joined_count += 1
                    group_name = await self._get_group_name(page)
                    if group_name:
                        group_names.append(group_name)
                    await self._browse_group(page)
                return {"success": True, "message": "Join group completed", "data": {"joined": joined_count, "group_names": group_names}}

            await page.goto("https://www.facebook.com/groups/discover", timeout=60000)
            await asyncio.sleep(random.uniform(2, 8))

            for _ in range(5):
                await page.mouse.wheel(0, 1500)
                await asyncio.sleep(random.uniform(2, 8))

            group_links = await page.query_selector_all('a[href*="/groups/"]')
            random.shuffle(group_links)

            for link in group_links:
                if joined_count >= max_count:
                    break
                href = await link.get_attribute("href")
                if not href:
                    continue
                await page.goto(href, timeout=60000)
                await asyncio.sleep(random.uniform(2, 8))
                joined = await self._join_current_group(page, logger)
                if joined:
                    joined_count += 1
                    group_name = await self._get_group_name(page)
                    if group_name:
                        group_names.append(group_name)
                    await self._browse_group(page)
                await asyncio.sleep(random.uniform(2, 8))

        except Exception as e:
            logger.warning(f"加入群组异常: {e}")
            return {"success": False, "message": str(e), "data": {"joined": joined_count, "group_names": group_names}}

        return {"success": True, "message": "Join group completed", "data": {"joined": joined_count, "group_names": group_names}}

    async def _join_current_group(self, page, logger) -> bool:
        join_selectors = [
            'div[aria-label="Join group"]',
            'div[aria-label="加入群组"]',
            'div[role="button"][aria-label="Join group"]',
        ]
        for selector in join_selectors:
            button = await page.query_selector(selector)
            if button:
                await button.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(2, 8))
                await button.click()
                await asyncio.sleep(random.uniform(2, 8))
                return True
        logger.info("未找到加入按钮")
        return False

    async def _get_group_name(self, page) -> str:
        title_element = await page.query_selector("h1")
        if not title_element:
            return ""
        return (await title_element.inner_text()).strip()

    async def _browse_group(self, page):
        browse_seconds = random.uniform(120, 300)
        start_time = time.time()
        while time.time() - start_time < browse_seconds:
            await page.mouse.wheel(0, 1200)
            await asyncio.sleep(random.uniform(2, 8))
