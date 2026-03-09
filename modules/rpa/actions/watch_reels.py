from modules.rpa.base import BaseAction, register_action
import random
import asyncio

@register_action
class WatchReelsAction(BaseAction):
    action_id = "rpa.watch_reels"
    
    async def execute(self, page, params, logger) -> dict:
        count = params.get("count", 5)
        min_watch = params.get("min_watch_seconds", 10)
        
        logger.info(f"Watching {count} reels")
        
        try:
            await page.goto("https://www.facebook.com/reel", timeout=60000)
            await asyncio.sleep(5) # Wait load
            
            for i in range(count):
                logger.info(f"Watching reel {i+1}/{count}")
                # Watch
                wait_time = min_watch + random.uniform(0, 10)
                await asyncio.sleep(wait_time)
                
                # Next reel
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(random.uniform(1, 2))
                
        except Exception as e:
            logger.warning(f"Error in watch reels: {e}")
            return {"success": False, "message": str(e)}
            
        return {"success": True, "message": f"Watched {count} reels"}
