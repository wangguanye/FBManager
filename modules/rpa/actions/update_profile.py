"""更新个人资料动作
参数：field(str), value(str)
"""
import asyncio
import random

from modules.rpa.base import BaseAction, register_action

@register_action
class UpdateProfileAction(BaseAction):
    action_id = "rpa.update_profile"

    async def execute(self, page, params, logger) -> dict:
        field = params.get("field")
        value = params.get("value")
        if not field or value is None:
            return {"success": False, "message": "invalid_params", "data": {"updated": False, "field": field}}

        try:
            if field == "privacy":
                if value != "friends_only":
                    return {"success": False, "message": "unsupported_value", "data": {"updated": False, "field": field}}
                await page.goto("https://www.facebook.com/settings/privacy", timeout=60000)
                await asyncio.sleep(random.uniform(2, 8))
                friends_button = await page.query_selector('text="Friends"')
                if friends_button:
                    await friends_button.click()
                    await asyncio.sleep(random.uniform(2, 8))
                return {"success": True, "message": "privacy_updated", "data": {"updated": True, "field": field}}

            await page.goto("https://www.facebook.com/profile", timeout=60000)
            await asyncio.sleep(random.uniform(2, 8))

            edit_button = await page.query_selector('text="Edit profile"')
            if edit_button:
                await edit_button.click()
                await asyncio.sleep(random.uniform(2, 8))

            field_selectors = {
                "city": ['text="Current city"', 'text="现居城市"'],
                "hometown": ['text="Hometown"', 'text="家乡"'],
                "school": ['text="Education"', 'text="学校"'],
                "workplace": ['text="Work"', 'text="工作单位"'],
                "bio": ['text="Bio"', 'text="简介"'],
                "birthday": ['text="Birthday"', 'text="生日"'],
                "gender": ['text="Gender"', 'text="性别"'],
                "language": ['text="Languages"', 'text="语言"'],
                "relationship": ['text="Relationship"', 'text="感情状况"'],
                "website": ['text="Website"', 'text="网站"'],
            }
            if field not in field_selectors:
                return {"success": False, "message": "unsupported_field", "data": {"updated": False, "field": field}}

            target_selector_list = field_selectors[field]
            clicked = False
            for selector in target_selector_list:
                target = await page.query_selector(selector)
                if target:
                    await target.click()
                    clicked = True
                    await asyncio.sleep(random.uniform(2, 8))
                    break

            if not clicked:
                return {"success": False, "message": "field_not_found", "data": {"updated": False, "field": field}}

            input_box = await page.query_selector('input[type="text"], textarea, div[role="textbox"]')
            if not input_box:
                return {"success": False, "message": "input_not_found", "data": {"updated": False, "field": field}}

            await input_box.fill("")
            await asyncio.sleep(random.uniform(2, 8))
            for ch in value:
                await input_box.type(ch)
                await asyncio.sleep(random.uniform(0.05, 0.15))

            save_button = await page.query_selector('text="Save"')
            if save_button:
                await save_button.click()
                await asyncio.sleep(random.uniform(2, 8))
                return {"success": True, "message": "profile_updated", "data": {"updated": True, "field": field}}

        except Exception as e:
            logger.warning(f"更新个人资料异常: {e}")
            return {"success": False, "message": str(e), "data": {"updated": False, "field": field}}

        return {"success": False, "message": "update_failed", "data": {"updated": False, "field": field}}
