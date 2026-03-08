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
