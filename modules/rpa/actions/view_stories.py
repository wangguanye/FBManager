import asyncio
import random

from modules.rpa.base import BaseAction, register_action

@register_action
class ViewStoriesAction(BaseAction):
    action_id = "rpa.view_stories"

    async def execute(self, page, params, logger) -> dict:
        count = params.get("count", 5)
        viewed = 0
        min_stay_seconds = 3
        max_stay_seconds = 8
        min_gap_seconds = 1
        max_gap_seconds = 3

        logger.info(f"Viewing stories: {count}")

        try:
            await page.goto("https://www.facebook.com/", timeout=60000)
            await asyncio.sleep(random.uniform(2, 5))
            container = await page.query_selector('div[class*="stories"]')
            if not container:
                return {"success": False, "message": "stories_container_not_found", "viewed": 0, "data": {"viewed": 0}}
            thumbnails = await container.query_selector_all('a, div[role="button"]')
            if not thumbnails:
                return {"success": False, "message": "stories_thumbnail_not_found", "viewed": 0, "data": {"viewed": 0}}

            await thumbnails[0].click()
            await asyncio.sleep(random.uniform(2, 4))

            while viewed < count:
                try:
                    await page.wait_for_selector('div[role="dialog"], video, img', timeout=10000)
                except Exception:
                    pass

                await asyncio.sleep(random.uniform(min_stay_seconds, max_stay_seconds))
                viewed += 1

                if viewed >= count:
                    break

                next_clicked = False
                for selector in [
                    'div[aria-label="Next"]',
                    'div[aria-label="下一则"]',
                    'div[role="button"][aria-label="Next"]',
                    'div[role="button"][aria-label="下一则"]'
                ]:
                    next_button = await page.query_selector(selector)
                    if next_button:
                        await next_button.click()
                        next_clicked = True
                        break

                if not next_clicked:
                    await page.keyboard.press("ArrowRight")

                await asyncio.sleep(random.uniform(min_gap_seconds, max_gap_seconds))

            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"View stories error: {e}")
            return {"success": False, "message": str(e), "viewed": viewed, "data": {"viewed": viewed}}

        return {"success": True, "message": "view_stories_completed", "viewed": viewed, "data": {"viewed": viewed}}
