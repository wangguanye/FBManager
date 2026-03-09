from modules.rpa.base import BaseAction, register_action
import asyncio

@register_action
class CheckStatusAction(BaseAction):
    action_id = "rpa.check_status"
    
    async def execute(self, page, params, logger) -> dict:
        logger.info("Checking account status...")
        
        try:
            if "facebook.com" not in page.url:
                await page.goto("https://www.facebook.com/", timeout=60000)
                await asyncio.sleep(5)
            
            content = await page.content()
            content_lower = content.lower()
            
            if "account disabled" in content_lower or "your account has been disabled" in content_lower or "帐户已停用" in content:
                logger.critical("Detected: Account Disabled")
                return {"success": True, "message": "Status checked", "data": {"status": "disabled", "action": "cascade_ban"}}

            if "confirm your identity" in content_lower or "验证身份" in content:
                logger.warning("Detected: Verification Required")
                return {"success": True, "message": "Status checked", "data": {"status": "verification_required", "action": "pause"}}

            if "suspicious login attempt" in content_lower:
                logger.warning("Detected: Suspicious Login Attempt")
                return {"success": True, "message": "Status checked", "data": {"status": "suspicious", "action": "pause"}}

            if "what's on your mind" in content_lower or "news feed" in content_lower or "stories" in content_lower:
                return {"success": True, "message": "Status checked", "data": {"status": "healthy"}}

            return {"success": True, "message": "Status checked", "data": {"status": "healthy"}}
                
        except Exception as e:
            logger.warning(f"Error checking status: {e}")
            return {"success": False, "message": str(e), "data": {"status": "unknown"}}
