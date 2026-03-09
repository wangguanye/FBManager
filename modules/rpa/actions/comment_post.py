"""评论帖子动作
参数：max_count(int), comment_pool(str, default='en')
"""
import asyncio
import random

from modules.rpa.base import BaseAction, register_action
from db.database import AsyncSessionLocal
from modules.asset.service import pick_comment

@register_action
class CommentPostAction(BaseAction):
    action_id = "rpa.comment_post"

    async def execute(self, page, params, logger) -> dict:
        max_count = params.get("max_count", 1)
        comment_pool = params.get("comment_pool", "en")
        commented_count = 0

        logger.info(f"开始评论帖子，最大数量: {max_count}, 语料库: {comment_pool}")

        try:
            await page.goto("https://www.facebook.com/", timeout=60000)
            await asyncio.sleep(random.uniform(2, 8))

            comment_button_selector = 'div[aria-label="Leave a comment"], div[aria-label="发表评论"], div[aria-label="Comment"]'
            for _ in range(max_count):
                comment_buttons = await page.query_selector_all(comment_button_selector)
                if not comment_buttons:
                    break

                button = random.choice(comment_buttons)
                await button.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(2, 8))
                await button.click()
                await asyncio.sleep(random.uniform(2, 8))

                async with AsyncSessionLocal() as db:
                    comment_item = await pick_comment(db, language=comment_pool)
                    if not comment_item:
                        logger.warning("评论语料库为空")
                        return {"success": True, "message": "empty_pool", "data": {"commented": 0, "reason": "empty_pool"}}

                input_box = await page.query_selector('div[role="textbox"]')
                if not input_box:
                    continue

                for ch in comment_item.content:
                    await input_box.type(ch)
                    await asyncio.sleep(random.uniform(0.05, 0.15))

                await input_box.press("Enter")
                commented_count += 1
                await asyncio.sleep(random.uniform(60, 180))

        except Exception as e:
            logger.warning(f"评论帖子异常: {e}")
            return {"success": False, "message": str(e), "data": {"commented": commented_count}}

        return {"success": True, "message": "Comment post completed", "data": {"commented": commented_count}}
