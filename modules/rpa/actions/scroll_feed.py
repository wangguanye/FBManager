from modules.rpa.base import BaseAction, register_action
import random
import asyncio
import time

@register_action
class ScrollFeedAction(BaseAction):
    action_id = "rpa.scroll_feed"

    async def execute(self, page, params, logger) -> dict:
        duration_min = params.get("duration_min", 5)
        logger.info(f"Scrolling feed for {duration_min} minutes")
        
        try:
            await page.goto("https://www.facebook.com/", timeout=60000)
            # Wait for feed or just wait a bit
            try:
                await page.wait_for_selector('div[role="feed"]', timeout=10000)
            except Exception:
                logger.warning("Feed selector not found, continuing anyway.")
        except Exception as e:
            logger.warning(f"Error navigating to Facebook: {e}")
            # Don't crash, try to scroll anyway
        
        end_time = time.time() + duration_min * 60
        
        while time.time() < end_time:
            scroll_px = random.randint(300, 800)
            await page.mouse.wheel(0, scroll_px)
            
            # Interval 2-5s
            await asyncio.sleep(random.uniform(2, 5))
            
            # Random pause 5-15s (simulate reading)
            if random.random() < 0.3: 
                await asyncio.sleep(random.uniform(5, 15))
                
        return {"success": True, "message": "Scroll feed completed"}
