import sqlite3
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine

# SQLite 数据库文件路径
DATABASE_URL = "sqlite+aiosqlite:///./fb_manager.db"

# 创建异步引擎
engine = create_async_engine(DATABASE_URL, echo=False)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 声明基类
class Base(DeclarativeBase):
    pass

# 获取数据库会话的依赖项
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# 用于同步操作的引擎（可选）
sync_engine = create_engine("sqlite:///./fb_manager.db")


def ensure_browser_window_columns(db_path: str = "./fb_manager.db"):
    """Auto-add new columns to browser_windows if they don't exist yet."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    existing = [row[1] for row in cursor.execute("PRAGMA table_info(browser_windows)")]
    new_cols = {
        "synced_proxy_host": "TEXT",
        "synced_proxy_port": "INTEGER",
        "synced_proxy_type": "TEXT",
        "synced_proxy_username": "TEXT",
        "synced_username": "TEXT",
        "is_running": "INTEGER DEFAULT 0",
        "remark": "TEXT",
        "last_synced_at": "DATETIME",
    }
    for col_name, col_type in new_cols.items():
        if col_name not in existing:
            cursor.execute(f"ALTER TABLE browser_windows ADD COLUMN {col_name} {col_type}")
    conn.commit()
    conn.close()

