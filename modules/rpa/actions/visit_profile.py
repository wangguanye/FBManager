import asyncio
import random
import time

from modules.rpa.base import BaseAction, register_action

META = {
    "action_id": "visit_profile",
    "name": "访问用户主页",
    "params_schema": {
        "target_url": {"type": "string", "label": "目标主页链接", "default": ""},
        "browse_seconds": {"type": "number", "label": "浏览秒数", "default": 10}
    }
}

@register_action
class VisitProfileAction(BaseAction):
    action_id = "rpa.visit_profile"

    async def execute(self, page, params, logger) -> dict:
        target_url = params.get("target_url")
        browse_seconds = params.get("browse_seconds")
        if browse_seconds is None:
            browse_seconds = random.randint(5, 15)

        profile_url = None
        visited = False

        try:
            if target_url:
                profile_url = target_url
                await page.goto(target_url, timeout=60000)
            else:
                await page.goto("https://www.facebook.com/", timeout=60000)
                await asyncio.sleep(random.uniform(2, 5))
                try:
                    await page.wait_for_selector('div[role="feed"]', timeout=10000)
                except Exception:
                    pass

                links = await page.query_selector_all('a[role="link"]')
                candidate_urls = []
                blocked_keywords = [
                    "/groups/",
                    "/watch/",
                    "/reel/",
                    "/stories/",
                    "/marketplace/",
                    "/events/",
                    "/pages/",
                    "/ads/",
                    "/gaming/",
                    "/business/"
                ]

                for link in links:
                    href = await link.get_attribute("href")
                    if not href or "facebook.com" not in href:
                        continue
                    if any(keyword in href for keyword in blocked_keywords):
                        continue
                    if "profile.php" in href or "/people/" in href:
                        candidate_urls.append(href)

                if not candidate_urls:
                    for link in links:
                        href = await link.get_attribute("href")
                        if not href or "facebook.com" not in href:
                            continue
                        if any(keyword in href for keyword in blocked_keywords):
                            continue
                        candidate_urls.append(href)

                if not candidate_urls:
                    return {
                        "success": False,
                        "message": "profile_not_found",
                        "visited": False,
                        "profile_url": None,
                        "data": {"visited": False, "profile_url": None}
                    }

                profile_url = random.choice(candidate_urls)
                await page.goto(profile_url, timeout=60000)

            await asyncio.sleep(random.uniform(2, 4))

            tabs = await page.query_selector_all('a[role="tab"]')
            if tabs:
                tab = random.choice(tabs)
                await tab.click()
                await asyncio.sleep(random.uniform(2, 4))

            end_time = time.time() + browse_seconds
            while time.time() < end_time:
                await page.mouse.wheel(0, random.randint(300, 900))
                await asyncio.sleep(random.uniform(1, 2))

            try:
                await page.go_back()
            except Exception:
                pass

            visited = True

        except Exception as e:
            logger.warning(f"Visit profile error: {e}")
            return {
                "success": False,
                "message": str(e),
                "visited": False,
                "profile_url": profile_url,
                "data": {"visited": False, "profile_url": profile_url}
            }

        return {
            "success": True,
            "message": "visit_profile_completed",
            "visited": visited,
            "profile_url": profile_url,
            "data": {"visited": visited, "profile_url": profile_url}
        }
