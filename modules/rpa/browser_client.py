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
                # Some BitBrowser APIs return success=false with HTTP 200.
                pass
            return res_json
        except httpx.RequestError as e:
            logger.error(f"BitBrowser API connection failed: {e}")
            raise BitBrowserNotRunningError("无法连接到比特浏览器，请确认已启动")
        except httpx.HTTPStatusError as e:
            logger.error(f"BitBrowser API error: {e.response.text}")
            raise Exception(f"BitBrowser API Error: {e.response.text}")

    async def _post(self, endpoint: str, payload: Dict[str, Any]) -> Any:
        return await self._request("POST", endpoint, json=payload)

    async def open_browser(self, profile_id: str) -> Dict[str, str]:
        """POST /browser/open, body={id,args,loadExtensions}"""
        payload = {
            "id": profile_id,
            "args": [],
            "loadExtensions": True,
        }
        res = await self._post("/browser/open", payload)
        data = res.get("data", {})
        return {
            "ws": data.get("ws"),
            "http": data.get("http"),
        }

    async def close_browser(self, profile_id: str) -> bool:
        """POST /browser/close, body={id}"""
        payload = {"id": profile_id}
        await self._post("/browser/close", payload)
        return True

    async def delete_browser(self, profile_id: str) -> bool:
        """POST /browser/delete 删除比特浏览器窗口"""
        payload = {"id": profile_id}
        await self._post("/browser/delete", payload)
        return True

    async def get_browser_detail(self, profile_id: str) -> Dict[str, Any]:
        """Get detailed profile info including proxy config from BitBrowser."""
        resp = await self._post("/browser/detail", {"id": profile_id})
        return resp.get("data", {}) if isinstance(resp, dict) else {}

    async def list_browsers(self, page: int = 0, page_size: int = 100) -> List[Dict[str, Any]]:
        """POST /browser/list, body={page,pageSize}"""
        payload = {
            "page": page,
            "pageSize": page_size,
        }
        res = await self._post("/browser/list", payload)
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
