import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from loguru import logger
import yaml
import os

from db.database import engine, Base, ensure_browser_window_columns
from modules.asset.router import router as asset_router
from modules.ad.router import router as ad_router
from modules.monitor.router import router as monitor_router
from modules.nurture.router import router as nurture_router
from modules.system.router import router as system_router
from modules.health.router import router as health_router
from modules.sop.router import router as sop_router
from modules.system.service import perform_backup, perform_log_cleanup
from core.scheduler import start_scheduler, stop_scheduler
from modules.asset.models import FBAccount, ProxyIP, BrowserWindow, CommentPool, AvatarAsset
from modules.ad.models import BMAccount, AdAccount, Fanpage, BudgetChange, AdDailyStat
from modules.monitor.models import NurtureTask, ActionLog, Alert
from modules.health.models import HealthScore

# 加载业务配置
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.join("assets", "avatars"), exist_ok=True)
    os.makedirs(os.path.join("assets", "covers"), exist_ok=True)
    # 启动时自动建表
    logger.info("正在初始化数据库表...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ensure_browser_window_columns()
    logger.info("数据库初始化完成")

    # 执行系统维护任务
    logger.info("执行系统维护：数据库备份...")
    await perform_backup()
    logger.info("执行系统维护：清理旧日志...")
    await perform_log_cleanup()

    # 启动调度器
    await start_scheduler()
    logger.info("调度器已启动")

    yield

    # 停止调度器
    await stop_scheduler()
    logger.info("调度器已停止")

app = FastAPI(
    title="FBManager",
    description="Facebook 账号管理与自动化养号系统",
    version="1.0.0",
    lifespan=lifespan
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/static-assets", StaticFiles(directory="assets"), name="assets")

# 配置 Jinja2 模板
templates = Jinja2Templates(directory="templates")

# 注册 API 路由
app.include_router(asset_router, prefix="/api")
app.include_router(ad_router, prefix="/api")
app.include_router(monitor_router, prefix="/api")
app.include_router(nurture_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(sop_router)

@app.get("/")
async def index(request: Request):
    """首页渲染"""
    return templates.TemplateResponse("dashboard.html", {"request": request, "title": "仪表盘"})

@app.get("/accounts")
async def accounts_page(request: Request):
    """账号管理页面"""
    return templates.TemplateResponse("accounts.html", {"request": request, "title": "账号管理"})

@app.get("/proxies")
async def proxies_page(request: Request):
    """代理管理页面"""
    return templates.TemplateResponse("proxies.html", {"request": request, "title": "代理管理"})

@app.get("/windows")
async def windows_page(request: Request):
    """窗口管理页面"""
    return templates.TemplateResponse("windows.html", {"request": request, "title": "窗口管理"})

@app.get("/tasks")
async def tasks_page(request: Request):
    """任务管理页面"""
    return templates.TemplateResponse("tasks.html", {"request": request, "title": "养号任务"})

@app.get("/ads")
async def ads_page(request: Request):
    """广告投放页面"""
    return templates.TemplateResponse("ads.html", {"request": request, "title": "广告账户"})

@app.get("/logs")
async def logs_page(request: Request):
    """日志页面"""
    return templates.TemplateResponse("logs.html", {"request": request, "title": "日志查看"})

@app.get("/sop")
async def sop_page(request: Request):
    """SOP 编辑器页面"""
    return templates.TemplateResponse("sop.html", {"request": request, "title": "SOP 编辑器"})

@app.get("/nurture")
async def nurture_page(request: Request):
    """养号流程页面"""
    return templates.TemplateResponse("base.html", {"request": request, "title": "养号流程"})

@app.get("/rpa")
async def rpa_page(request: Request):
    """RPA 脚本页面"""
    return templates.TemplateResponse("base.html", {"request": request, "title": "RPA 脚本"})

@app.get("/assets")
async def assets_page(request: Request):
    """资源管理页面"""
    return templates.TemplateResponse("assets.html", {"request": request, "title": "语料&素材"})

if __name__ == "__main__":
    # 仅监听 127.0.0.1:8000
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
