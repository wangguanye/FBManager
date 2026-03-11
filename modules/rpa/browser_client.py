import httpx
from typing import Any, Dict, List
from loguru import logger


class BitBrowserNotRunningError(Exception):
    """比特浏览器未运行异常"""
    pass


class BitBrowserClient:
    BASE_URL = "http://127.0.0.1:54345"

    def __init__(self):
        self.client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=10.0)

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        try:
            response = await self.client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            res_json = response.json()
            if not res_json.get("success", True):
                # 有些 API 返回 success 字段，保持与历史逻辑一致
                pass
            return res_json
        except httpx.RequestError as e:
            logger.error(f"BitBrowser API connection failed: {e}")
            raise BitBrowserNotRunningError("无法连接到比特浏览器，请确认已启动")
        except httpx.HTTPStatusError as e:
            logger.error(f"BitBrowser API error: {e.response.text}")
            raise Exception(f"BitBrowser API Error: {e.response.text}")

    async def open_browser(self, profile_id: str) -> Dict[str, str]:
        """POST /browser/open，body={id,args,loadExtensions}"""
        payload = {
            "id": profile_id,
            "args": [],
            "loadExtensions": True,
        }
        res = await self._request("POST", "/browser/open", json=payload)
        data = res.get("data", {})
        return {
            "ws": data.get("ws"),
            "http": data.get("http"),
        }

    async def close_browser(self, profile_id: str) -> bool:
        """POST /browser/close，body={id}"""
        payload = {"id": profile_id}
        await self._request("POST", "/browser/close", json=payload)
        return True

    async def list_browsers(self, page: int = 0, page_size: int = 100) -> List[Dict[str, Any]]:
        """POST /browser/list，body={page,pageSize}"""
        payload = {
            "page": page,
            "pageSize": page_size,
        }
        res = await self._request("POST", "/browser/list", json=payload)
        data = res.get("data", {})
        if isinstance(data, dict):
            return data.get("list", [])
        return data if isinstance(data, list) else []

    async def check_alive(self) -> bool:
        """检查比特浏览器是否运行"""
        try:
            async with httpx.AsyncClient(base_url=self.BASE_URL, timeout=2.0) as client:
                await client.get("/")
                return True
        except Exception:
            return False

    async def get_browser_detail(self, profile_id: str) -> dict:
        """GET single window detail including proxy config.
        POST /browser/detail  body: {"id": profile_id}
        Returns dict with: id, name, remark, proxyMethod, proxyType, host, port, proxyUserName
        """
        try:
            res = await self._request("POST", "/browser/detail", json={"id": profile_id})
            return res.get("data", {})
        except Exception as e:
            logger.warning(f"get_browser_detail failed for {profile_id}: {e}")
            return {}

    async def delete_browser(self, profile_id: str) -> bool:
        """Delete a browser window.
        POST /browser/delete  body: {"id": profile_id}
        """
        await self._request("POST", "/browser/delete", json={"id": profile_id})
        return True
