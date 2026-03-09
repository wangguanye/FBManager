"""添加好友动作
参数：max_count(int), target_region(str, default='US')
"""
import asyncio
import random
from modules.rpa.base import BaseAction, register_action

@register_action
class AddFriendAction(BaseAction):
    action_id = "rpa.add_friend"

    async def execute(self, page, params, logger) -> dict:
        max_count = params.get("max_count", 3)
        target_region = params.get("target_region", "US")
        added_count = 0
        skipped_count = 0

        logger.info(f"开始添加好友，目标地区: {target_region}, 最大数量: {max_count}")

        try:
            await page.goto("https://www.facebook.com/find-friends", timeout=60000)
            await asyncio.sleep(random.uniform(2, 8))

            for _ in range(10):
                await page.mouse.wheel(0, 1200)
                await asyncio.sleep(random.uniform(2, 8))

            add_button_selector = 'div[aria-label="Add Friend"], div[aria-label="添加好友"], div[role="button"][aria-label="Add Friend"]'

            while added_count < max_count:
                add_buttons = await page.query_selector_all(add_button_selector)
                if not add_buttons:
                    break

                for button in add_buttons:
                    if added_count >= max_count:
                        break
                    try:
                        await button.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(2, 8))

                        profile_link = await button.evaluate("el => el.closest('div')?.querySelector('a[href*=\"facebook.com\"]')?.getAttribute('href')")
                        if profile_link:
                            await page.goto(profile_link, timeout=60000)
                            await asyncio.sleep(random.uniform(5, 15))
                            await page.go_back()
                            await asyncio.sleep(random.uniform(2, 8))

                        await button.click()
                        added_count += 1
                        await asyncio.sleep(random.uniform(30, 90))
                    except Exception as e:
                        skipped_count += 1
                        logger.warning(f"跳过一个推荐用户: {e}")

                await page.mouse.wheel(0, 1500)
                await asyncio.sleep(random.uniform(2, 8))

        except Exception as e:
            logger.warning(f"添加好友异常: {e}")
            return {"success": False, "message": str(e), "data": {"added": added_count, "skipped": skipped_count}}

        return {"success": True, "message": "Add friend completed", "data": {"added": added_count, "skipped": skipped_count}}
