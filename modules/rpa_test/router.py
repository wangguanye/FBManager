from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from modules.rpa_test.service import RpaTestService

router = APIRouter(prefix="/api/rpa-test", tags=["rpa-test"])


class RunTestRequest(BaseModel):
    account_id: int
    action_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    keep_open: bool = False


class RunAllRequest(BaseModel):
    account_id: int
    keep_open: bool = False


@router.get("/modules")
async def list_modules(db: AsyncSession = Depends(get_db)):
    return await RpaTestService.get_modules(db)


@router.post("/run")
async def run_single_test(req: RunTestRequest):
    return await RpaTestService.start_single(
        account_id=req.account_id,
        action_id=req.action_id,
        params=req.params,
        keep_open=req.keep_open,
    )


@router.post("/run-all")
async def run_all_tests(req: RunAllRequest, db: AsyncSession = Depends(get_db)):
    return await RpaTestService.run_all(
        db=db,
        account_id=req.account_id,
        keep_open=req.keep_open,
    )


@router.get("/logs/{test_id}")
async def get_test_logs(test_id: str):
    return RpaTestService.get_logs(test_id)


@router.get("/results")
async def list_results(limit: int = 100, db: AsyncSession = Depends(get_db)):
    return await RpaTestService.list_results(db, limit=limit)


@router.get("/results/{action_id}")
async def get_module_result(action_id: str, db: AsyncSession = Depends(get_db)):
    return await RpaTestService.get_latest_result(db, action_id)
