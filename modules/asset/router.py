from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from db.database import get_db
from modules.asset import service, schemas

router = APIRouter(prefix="/asset", tags=["Asset"])

@router.post("/accounts", response_model=schemas.FBAccount)
async def create_account(account: schemas.FBAccountCreate, db: AsyncSession = Depends(get_db)):
    """创建 FB 账号"""
    return await service.create_fb_account(db, account)

@router.get("/accounts", response_model=List[schemas.FBAccount])
async def list_accounts(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """列出 FB 账号"""
    return await service.get_fb_accounts(db, skip, limit)

@router.post("/proxies", response_model=schemas.ProxyIP)
async def create_proxy(proxy: schemas.ProxyIPCreate, db: AsyncSession = Depends(get_db)):
    """创建代理 IP"""
    return await service.create_proxy(db, proxy)

@router.get("/proxies", response_model=List[schemas.ProxyIP])
async def list_proxies(db: AsyncSession = Depends(get_db)):
    """列出所有代理 IP"""
    return await service.get_proxies(db)

@router.post("/browser-windows", response_model=schemas.BrowserWindow)
async def create_browser_window(window: schemas.BrowserWindowCreate, db: AsyncSession = Depends(get_db)):
    """创建浏览器窗口"""
    return await service.create_browser_window(db, window)

@router.get("/browser-windows", response_model=List[schemas.BrowserWindow])
async def list_browser_windows(db: AsyncSession = Depends(get_db)):
    """列出所有浏览器窗口"""
    return await service.get_browser_windows(db)
