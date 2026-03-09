"""开启双重验证动作
参数：method(str, default='totp')
"""
import asyncio
import random
import re

import pyotp

from modules.rpa.base import BaseAction, register_action
from db.database import AsyncSessionLocal
from modules.asset.models import FBAccount
from core.crypto import encrypt_value

@register_action
class Enable2FAAction(BaseAction):
    action_id = "rpa.enable_2fa"

    async def execute(self, page, params, logger) -> dict:
        method = params.get("method", "totp")
        account_id = params.get("account_id")
        if method != "totp":
            return {"success": False, "message": "unsupported_method", "data": {"enabled": False, "method": method}}
        if not account_id:
            return {"success": False, "message": "missing_account_id", "data": {"enabled": False, "method": method}}

        try:
            await page.goto("https://www.facebook.com/settings?tab=security", timeout=60000)
            await asyncio.sleep(random.uniform(2, 8))
            await self._click_first(page, [
                'text="Two-factor authentication"',
                'text="双重验证"',
                'text="Two-factor Authentication"'
            ])
            await asyncio.sleep(random.uniform(2, 8))
            await self._click_first(page, [
                'text="Authentication app"',
                'text="身份验证应用"',
                'text="Authentication App"'
            ])
            await asyncio.sleep(random.uniform(2, 8))

            secret_key = await self._extract_secret_key(page)
            if not secret_key:
                return {"success": False, "message": "secret_not_found", "data": {"enabled": False, "method": method}}
            assert secret_key

            verification_code = pyotp.TOTP(secret_key).now()
            input_box = await page.query_selector('input[autocomplete="one-time-code"], input[type="text"]')
            if not input_box:
                return {"success": False, "message": "code_input_not_found", "data": {"enabled": False, "method": method}}
            await input_box.fill(verification_code)
            await asyncio.sleep(random.uniform(2, 8))
            await self._click_first(page, ['text="Continue"', 'text="Confirm"', 'text="继续"', 'text="确认"'])
            await asyncio.sleep(random.uniform(2, 8))

            async with AsyncSessionLocal() as db:
                account = await db.get(FBAccount, account_id)
                if account:
                    account.totp_secret_encrypted = encrypt_value(secret_key)
                    db.add(account)
                    await db.commit()

            return {"success": True, "message": "2fa_enabled", "data": {"enabled": True, "method": method}}

        except Exception as e:
            logger.warning(f"开启双重验证异常: {e}")
            return {"success": False, "message": str(e), "data": {"enabled": False, "method": method}}

    async def _extract_secret_key(self, page) -> str | None:
        content = await page.content()
        match = re.search(r"\b[A-Z2-7]{16,}\b", content)
        if match:
            return match.group(0)
        return None

    async def _click_first(self, page, selectors: list[str]) -> None:
        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                await element.click()
                return
