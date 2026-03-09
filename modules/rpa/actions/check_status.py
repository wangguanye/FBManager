from modules.rpa.base import BaseAction, register_action
import asyncio

@register_action
class CheckStatusAction(BaseAction):
    action_id = "rpa.check_status"
    
    async def execute(self, page, params, logger) -> dict:
        logger.info("Checking account status...")
        
        status = "normal"
        try:
            # Assume we are on a page, or navigate to home
            if "facebook.com" not in page.url:
                await page.goto("https://www.facebook.com/", timeout=60000)
                await asyncio.sleep(5)
            
            content = await page.content()
            url = page.url
            
            # Keywords check
            if "checkpoint" in url or "验证身份" in content or "Confirm Your Identity" in content:
                status = "verification_required"
                logger.warning("Detected: Verification Required")
            elif "disabled" in url or "Account Disabled" in content or "帐户已停用" in content:
                status = "disabled"
                logger.critical("Detected: Account Disabled")
                
        except Exception as e:
            logger.warning(f"Error checking status: {e}")
            return {"success": False, "message": str(e), "data": {"status": "unknown"}}
            
        return {"success": True, "message": "Status checked", "data": {"status": status}}
