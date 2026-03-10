import asyncio
import random

from db.database import AsyncSessionLocal
from modules.asset.service import pick_comment
from modules.rpa.base import BaseAction, register_action

META = {
    "action_id": "share_post",
    "name": "分享帖子",
    "params_schema": {
        "max_count": {"type": "number", "label": "最大数量", "default": 1},
        "comment_pool": {"type": "string", "label": "评论语料库", "default": "en"}
    }
}

@register_action
class SharePostAction(BaseAction):
    action_id = "rpa.share_post"

    async def execute(self, page, params, logger) -> dict:
        max_count = params.get("max_count", 1)
        shared = 0

        logger.info(f"Sharing posts: {max_count}")

        try:
            await page.goto("https://www.facebook.com/", timeout=60000)
            await asyncio.sleep(random.uniform(2, 5))
            try:
                await page.wait_for_selector('div[role="feed"]', timeout=10000)
            except Exception:
                pass

            for _ in range(max_count):
                share_buttons = await page.query_selector_all(
                    'div[aria-label="Share"], div[aria-label="分享"], div[role="button"][aria-label="Share"], div[role="button"][aria-label="分享"]'
                )
                if not share_buttons:
                    break

                target_button = random.choice(share_buttons)
                await target_button.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(1, 2))
                await target_button.click()
                await asyncio.sleep(random.uniform(2, 4))

                share_menu = None
                for selector in [
                    'div[role="menuitem"][aria-label="Share to your timeline"]',
                    'div[role="menuitem"][aria-label="分享到你的主页"]',
                    'div[role="menuitem"][aria-label="Share now"]',
                    'div[role="menuitem"][aria-label="立即分享"]'
                ]:
                    share_menu = await page.query_selector(selector)
                    if share_menu:
                        break

                if not share_menu:
                    break

                await share_menu.click()
                await asyncio.sleep(random.uniform(2, 4))

                async with AsyncSessionLocal() as db:
                    comment_item = await pick_comment(db, language=params.get("comment_pool", "en"))
                    comment_text = comment_item.content if comment_item else None

                if comment_text:
                    input_box = await page.query_selector('div[role="textbox"]')
                    if input_box:
                        await input_box.click()
                        for ch in comment_text:
                            await input_box.type(ch)
                            await asyncio.sleep(random.uniform(0.05, 0.12))

                share_now = None
                for selector in [
                    'div[aria-label="Post"]',
                    'div[aria-label="发布"]',
                    'div[aria-label="Share now"]',
                    'div[aria-label="立即分享"]'
                ]:
                    share_now = await page.query_selector(selector)
                    if share_now:
                        break

                if share_now:
                    await share_now.click()
                else:
                    await page.keyboard.press("Enter")

                shared += 1
                await asyncio.sleep(random.uniform(60, 120))

        except Exception as e:
            logger.warning(f"Share post error: {e}")
            return {"success": False, "message": str(e), "shared": shared, "data": {"shared": shared}}

        return {"success": True, "message": "share_post_completed", "shared": shared, "data": {"shared": shared}}
