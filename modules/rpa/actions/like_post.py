from modules.rpa.base import BaseAction, register_action
import random
import asyncio

@register_action
class LikePostAction(BaseAction):
    action_id = "rpa.like_post"
    
    async def execute(self, page, params, logger) -> dict:
        max_count = params.get("max_count", 3)
        count = 0
        
        logger.info(f"Attempting to like up to {max_count} posts")
        
        # Try to find like buttons
        # Facebook like buttons usually have aria-label="Like" or "赞"
        selector = 'div[aria-label="Like"], div[aria-label="赞"]'
        
        try:
            # Get multiple elements
            elements = await page.query_selector_all(selector)
            
            # Filter visible ones?
            # Randomly select
            targets = random.sample(elements, min(len(elements), max_count))
            
            for btn in targets:
                try:
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(1)
                    await btn.click()
                    count += 1
                    logger.info("Liked a post")
                    await self.random_delay()
                except Exception as e:
                    logger.warning(f"Failed to click like button: {e}")
                    
        except Exception as e:
            logger.warning(f"Error finding like buttons: {e}")
            
        return {"success": True, "message": f"Liked {count} posts"}
