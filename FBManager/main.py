import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from loguru import logger
import yaml
import os

from db.database import engine, Base
from modules.asset.router import router as asset_router
from modules.monitor.router import router as monitor_router
from core.scheduler import start_scheduler, stop_scheduler

# 加载业务配置
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自动建表
    logger.info("正在初始化数据库表...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库初始化完成")

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
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# 配置 Jinja2 模板
templates = Jinja2Templates(directory="templates")

# 注册 API 路由
app.include_router(asset_router, prefix="/api")
app.include_router(monitor_router, prefix="/api")

@app.get("/")
async def index(request: Request):
    """首页渲染"""
    return templates.TemplateResponse("base.html", {"request": request, "title": "仪表盘"})

if __name__ == "__main__":
    # 仅监听 127.0.0.1:8000
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
