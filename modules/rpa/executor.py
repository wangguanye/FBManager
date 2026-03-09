import asyncio
from typing import List, Dict, Any
from loguru import logger
from playwright.async_api import async_playwright
from datetime import datetime

from modules.rpa.base import ACTION_REGISTRY, BaseAction
from modules.rpa.browser_client import BitBrowserClient
from modules.monitor.models import ActionLog
from db.database import AsyncSessionLocal
# Import actions to ensure registration
import modules.rpa.actions

class RPAExecutor:
    def __init__(self):
        self.browser_client = BitBrowserClient()

    async def run_task(self, account, task, actions: List[Dict]):
        """
        Execute a list of actions for an account.
        :param account: FBAccount object
        :param task: NurtureTask object (optional, for logging context)
        :param actions: List of dicts, e.g. [{"action": "rpa.scroll_feed", "params": {...}}]
        """
        # 1. Check if BitBrowser is alive
        if not await self.browser_client.check_alive():
            logger.error("BitBrowser is not running.")
            return

        # Handle account.browser_window possibly being None
        if not account.browser_window:
            logger.error(f"Account {account.id} has no browser window assigned.")
            return
            
        window_id = account.browser_window.bit_window_id
        if not window_id:
            logger.error(f"Account {account.id} has no bit_window_id.")
            return

        logger.info(f"Starting RPA task for account {account.username} (Window {window_id})")
        
        playwright = None
        browser = None
        
        try:
            # 2. Open Browser
            # Note: browser_client.open_browser returns dict with 'ws' and 'http'
            res = await self.browser_client.open_browser(window_id)
            ws_endpoint = res.get("ws")
            if not ws_endpoint:
                logger.error(f"Failed to get WS endpoint for window {window_id}")
                return

            # 3. Connect via CDP
            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
            
            # 4. Get Page
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = await browser.new_context()
                
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()

            # 5. Execute Actions
            for action_config in actions:
                action_id = action_config.get("action")
                params = action_config.get("params", {})
                
                action_cls = ACTION_REGISTRY.get(action_id)
                if not action_cls:
                    logger.warning(f"Action {action_id} not found in registry.")
                    continue

                action_instance = action_cls()
                logger.info(f"Executing action: {action_id}")
                
                start_time = datetime.now()
                status = "failed"
                message = ""
                
                try:
                    result = await action_instance.execute(page, params, logger)
                    status = "success" if result.get("success", False) else "failed"
                    message = result.get("message", "")
                    
                    # Handle check_status specific logic
                    if action_id == "rpa.check_status":
                        check_data = result.get("data", {})
                        check_status = check_data.get("status")
                        if check_status == "disabled":
                            logger.critical(f"Account {account.id} is DISABLED!")
                            # TODO: Trigger cascade_ban logic here or outside
                        elif check_status == "verification_required":
                            logger.warning(f"Account {account.id} requires verification.")

                except Exception as e:
                    logger.error(f"Action {action_id} failed with exception: {e}")
                    message = str(e)
                    # 8. Exception handling: continue to next action
                
                # 6. Write action log
                async with AsyncSessionLocal() as db:
                    log = ActionLog(
                        fb_account_id=account.id,
                        task_id=task.id if task else None,
                        action_type=action_id,
                        level="INFO" if status == "success" else "ERROR",
                        message=f"{status}: {message}"[:500]
                    )
                    db.add(log)
                    await db.commit()

        except Exception as e:
            logger.error(f"RPA Execution failed: {e}")
        finally:
            # 7. Close browser
            if browser:
                # Disconnect CDP instead of closing to keep browser alive? 
                # No, user said "7. 全部完成后 close_browser", usually means closing the bitbrowser profile.
                await browser.close()
            if playwright:
                await playwright.stop()
            
            if window_id:
                await self.browser_client.close_browser(window_id)
