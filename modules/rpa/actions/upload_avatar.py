"""上传头像/封面动作
参数：type(str, default='both')
"""
import asyncio
import os
import random

from modules.rpa.base import BaseAction, register_action
from db.database import AsyncSessionLocal
from modules.asset.service import pick_avatar
from modules.asset.models import AvatarAsset

META = {
    "action_id": "upload_avatar",
    "name": "上传头像或封面",
    "params_schema": {
        "type": {
            "type": "select",
            "label": "上传类型",
            "options": ["avatar", "cover", "both"],
            "default": "both"
        },
        "account_id": {"type": "number", "label": "账号ID", "default": 0}
    }
}

@register_action
class UploadAvatarAction(BaseAction):
    action_id = "rpa.upload_avatar"

    async def execute(self, page, params, logger) -> dict:
        asset_type = params.get("type", "both")
        account_id = params.get("account_id")
        if asset_type not in ["avatar", "cover", "both"]:
            return {"success": False, "message": "invalid_type", "data": {"avatar_uploaded": False, "cover_uploaded": False}}
        if not account_id:
            return {"success": False, "message": "missing_account_id", "data": {"avatar_uploaded": False, "cover_uploaded": False}}

        avatar_uploaded = False
        cover_uploaded = False

        if asset_type in ["avatar", "both"]:
            avatar_asset = await self._pick_and_assign("avatar", account_id, logger)
            if not avatar_asset:
                return {"success": False, "message": "no_available_avatar", "data": {"avatar_uploaded": False, "cover_uploaded": False}}
            avatar_uploaded = await self._upload_profile_image(page, avatar_asset.file_path, logger)
            if not avatar_uploaded:
                await self._release_avatar(avatar_asset.id)
                return {"success": False, "message": "avatar_upload_failed", "data": {"avatar_uploaded": False, "cover_uploaded": False}}

        if asset_type in ["cover", "both"]:
            cover_asset = await self._pick_and_assign("cover", account_id, logger)
            if not cover_asset:
                return {"success": False, "message": "no_available_cover", "data": {"avatar_uploaded": avatar_uploaded, "cover_uploaded": False}}
            cover_uploaded = await self._upload_cover_image(page, cover_asset.file_path, logger)
            if not cover_uploaded:
                await self._release_avatar(cover_asset.id)
                return {"success": False, "message": "cover_upload_failed", "data": {"avatar_uploaded": avatar_uploaded, "cover_uploaded": False}}

        return {"success": True, "message": "upload_completed", "data": {"avatar_uploaded": avatar_uploaded, "cover_uploaded": cover_uploaded}}

    async def _pick_and_assign(self, asset_type: str, account_id: int, logger) -> AvatarAsset | None:
        async with AsyncSessionLocal() as db:
            avatar_asset = await pick_avatar(db, asset_type=asset_type)
            if not avatar_asset:
                logger.warning(f"{asset_type} 素材已用完")
                return None
            avatar_asset.used_by_account_id = account_id
            db.add(avatar_asset)
            await db.commit()
            await db.refresh(avatar_asset)
            return avatar_asset

    async def _release_avatar(self, avatar_id: int) -> None:
        async with AsyncSessionLocal() as db:
            avatar_asset = await db.get(AvatarAsset, avatar_id)
            if not avatar_asset:
                return
            avatar_asset.is_used = False
            avatar_asset.used_by_account_id = None
            db.add(avatar_asset)
            await db.commit()

    async def _upload_profile_image(self, page, file_path: str, logger) -> bool:
        absolute_path = os.path.abspath(file_path)
        if not os.path.exists(absolute_path):
            logger.warning(f"头像文件不存在: {absolute_path}")
            return False
        await page.goto("https://www.facebook.com/profile", timeout=60000)
        await asyncio.sleep(random.uniform(2, 8))
        await self._click_first(page, [
            'img[aria-label="Profile picture"]',
            'div[aria-label="Profile picture"]',
            'div[aria-label="头像"]'
        ])
        await asyncio.sleep(random.uniform(2, 8))
        file_input = await page.query_selector('input[type="file"]')
        if not file_input:
            return False
        await file_input.set_input_files(absolute_path)
        await asyncio.sleep(random.uniform(2, 8))
        await self._click_first(page, ['div[aria-label="Save"]', 'div[aria-label="保存"]', 'text="Save"', 'text="保存"'])
        await asyncio.sleep(random.uniform(2, 8))
        return True

    async def _upload_cover_image(self, page, file_path: str, logger) -> bool:
        absolute_path = os.path.abspath(file_path)
        if not os.path.exists(absolute_path):
            logger.warning(f"封面文件不存在: {absolute_path}")
            return False
        await page.goto("https://www.facebook.com/profile", timeout=60000)
        await asyncio.sleep(random.uniform(2, 8))
        await self._click_first(page, [
            'div[aria-label="Edit cover photo"]',
            'div[aria-label="编辑封面照片"]',
            'text="Edit cover photo"',
            'text="编辑封面照片"'
        ])
        await asyncio.sleep(random.uniform(2, 8))
        file_input = await page.query_selector('input[type="file"]')
        if not file_input:
            return False
        await file_input.set_input_files(absolute_path)
        await asyncio.sleep(random.uniform(2, 8))
        await self._click_first(page, ['div[aria-label="Save changes"]', 'div[aria-label="保存更改"]', 'text="Save"', 'text="保存"'])
        await asyncio.sleep(random.uniform(2, 8))
        return True

    async def _click_first(self, page, selectors: list[str]) -> None:
        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                await element.click()
                return
