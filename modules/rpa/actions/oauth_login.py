"""第三方 OAuth 登录动作
参数：target_site(str)，支持 canva / spotify / pinterest / eventbrite / change_org
"""
import asyncio
import random

from modules.rpa.base import BaseAction, register_action

META = {
    "action_id": "oauth_login",
    "name": "第三方 OAuth 登录",
    "params_schema": {
        "target_site": {
            "type": "select",
            "label": "目标站点",
            "options": ["canva", "spotify", "pinterest", "eventbrite", "change_org"],
            "default": "spotify"
        }
    }
}

@register_action
class OAuthLoginAction(BaseAction):
    action_id = "rpa.oauth_login"

    async def execute(self, page, params, logger) -> dict:
        target_site = params.get("target_site")
        site_map = {
            "canva": "https://www.canva.com/login",
            "spotify": "https://accounts.spotify.com/login",
            "pinterest": "https://www.pinterest.com/login",
            "eventbrite": "https://www.eventbrite.com/signin",
            "change_org": "https://www.change.org/sign_in",
        }
        if target_site not in site_map:
            return {"success": False, "message": "unsupported_site", "data": {"success": False, "site": target_site}}

        try:
            await page.goto(site_map[target_site], timeout=60000)
            await asyncio.sleep(random.uniform(2, 8))

            login_selectors = [
                'text="Continue with Facebook"',
                'text="Login with Facebook"',
                'text="Continue with Facebook"',
                'text="使用 Facebook 登录"',
            ]
            clicked = False
            for selector in login_selectors:
                button = await page.query_selector(selector)
                if button:
                    clicked = True
                    try:
                        async with page.expect_popup() as popup_info:
                            await button.click()
                        fb_popup = await popup_info.value
                        await asyncio.sleep(random.uniform(2, 8))
                        continue_button = await fb_popup.query_selector('text="Continue"')
                        if continue_button:
                            await continue_button.click()
                        await asyncio.sleep(random.uniform(2, 8))
                        await fb_popup.close()
                    except Exception:
                        await button.click()
                    break

            if not clicked:
                return {"success": False, "message": "facebook_login_not_found", "data": {"success": False, "site": target_site}}

            await asyncio.sleep(random.uniform(2, 8))
            await asyncio.sleep(random.uniform(30, 60))
            return {"success": True, "message": "OAuth login completed", "data": {"success": True, "site": target_site}}

        except Exception as e:
            logger.warning(f"OAuth 登录异常: {e}")
            return {"success": False, "message": str(e), "data": {"success": False, "site": target_site}}
