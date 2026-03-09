from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict
from db.database import get_db
from modules.asset import service, schemas
from modules.rpa.browser_client import BitBrowserNotRunningError

# 保持 API 统一前缀，这里不需要 /asset 前缀，因为 main.py 中已经挂载到 /api
router = APIRouter(tags=["Asset"])

# Accounts
@router.post("/accounts", response_model=schemas.FBAccount)
async def create_account(account: schemas.FBAccountCreate, db: AsyncSession = Depends(get_db)):
    """新增账号"""
    return await service.create_fb_account(db, account)

@router.post("/accounts/batch")
async def batch_import_accounts(import_data: schemas.FBAccountBatchImport, db: AsyncSession = Depends(get_db)):
    """批量导入账号"""
    return await service.batch_import_accounts(db, import_data.raw_text)

@router.get("/accounts", response_model=List[schemas.FBAccount])
async def list_accounts(
    skip: int = 0, 
    limit: int = 100, 
    status: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """账号列表，支持筛选和搜索"""
    return await service.get_fb_accounts(db, skip, limit, status, q)

@router.patch("/accounts/{id}", response_model=schemas.FBAccount)
async def update_account(
    id: int, 
    update_data: schemas.FBAccountUpdate, 
    db: AsyncSession = Depends(get_db)
):
    """编辑账号信息/状态"""
    account = await service.update_fb_account(db, id, update_data)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account

@router.delete("/accounts/{id}")
async def delete_account(id: int, db: AsyncSession = Depends(get_db)):
    """软删除账号"""
    success = await service.delete_fb_account(db, id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"code": 0, "msg": "Deleted successfully"}

@router.post("/accounts/{id}/bind", response_model=schemas.FBAccount)
async def bind_resources(
    id: int, 
    bind_data: schemas.FBAccountBind, 
    db: AsyncSession = Depends(get_db)
):
    """绑定代理和窗口"""
    return await service.bind_account_resources(db, id, bind_data)

# Proxies
@router.post("/proxies", response_model=schemas.ProxyIP, tags=["Proxies"])
async def create_proxy(proxy: schemas.ProxyIPCreate, db: AsyncSession = Depends(get_db)):
    """创建代理 IP"""
    return await service.create_proxy(db, proxy)

@router.post("/proxies/batch", tags=["Proxies"])
async def batch_import_proxies(import_data: schemas.ProxyIPBatchImport, db: AsyncSession = Depends(get_db)):
    """批量导入代理 IP"""
    return await service.batch_import_proxies(db, import_data.raw_text)

@router.get("/proxies", response_model=List[schemas.ProxyIP], tags=["Proxies"])
async def list_proxies(
    status: Optional[str] = None, 
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """列出所有代理 IP，支持筛选和搜索"""
    return await service.get_proxies(db, status, q)

@router.patch("/proxies/{id}", response_model=schemas.ProxyIP, tags=["Proxies"])
async def update_proxy(
    id: int, 
    update_data: schemas.ProxyIPUpdate, 
    db: AsyncSession = Depends(get_db)
):
    """编辑代理 IP"""
    proxy = await service.update_proxy(db, id, update_data)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return proxy

@router.delete("/proxies/{id}", status_code=204, tags=["Proxies"])
async def delete_proxy(id: int, db: AsyncSession = Depends(get_db)):
    """删除代理 IP"""
    await service.delete_proxy(db, id)
    return None

# Browser Windows
@router.post("/browser-windows", response_model=schemas.BrowserWindow, tags=["Windows"])
async def create_browser_window(window: schemas.BrowserWindowCreate, db: AsyncSession = Depends(get_db)):
    """创建浏览器窗口"""
    return await service.create_browser_window(db, window)

@router.get("/browser-windows", response_model=List[schemas.BrowserWindowDetail], tags=["Windows"])
async def list_browser_windows(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """列出所有浏览器窗口"""
    return await service.get_browser_windows(db, status)

@router.post("/windows/sync", tags=["Windows"])
async def sync_windows(db: AsyncSession = Depends(get_db)):
    """同步比特浏览器窗口列表"""
    try:
        result = await service.sync_browser_windows(db)
        return {"code": 0, "msg": "Sync successful", "data": result}
    except BitBrowserNotRunningError:
        raise HTTPException(status_code=503, detail="BitBrowser is not running")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@router.delete("/windows/{id}", status_code=204, tags=["Windows"])
async def delete_window(id: int, db: AsyncSession = Depends(get_db)):
    """删除浏览器窗口记录"""
    await service.delete_browser_window(db, id)
    return None

# Windows endpoints
@router.get("/windows", response_model=List[schemas.BrowserWindowDetail], tags=["Windows"])
async def list_windows(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """列出所有浏览器窗口 (Alias for /browser-windows to match frontend requirement)"""
    return await service.get_browser_windows(db, status)

@router.post("/windows/{id}/open", tags=["Windows"])
async def open_window(id: int, db: AsyncSession = Depends(get_db)):
    """打开浏览器窗口"""
    return await service.open_browser_window(db, id)

@router.post("/windows/{id}/close", tags=["Windows"])
async def close_window(id: int, db: AsyncSession = Depends(get_db)):
    """关闭浏览器窗口"""
    success = await service.close_browser_window(db, id)
    return {"code": 0, "msg": "Window closed"}
