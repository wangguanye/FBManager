from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from db.database import get_db
from modules.health import service, schemas

router = APIRouter()

@router.get("/health/scores", response_model=List[schemas.HealthScoreOut])
async def list_health_scores(
    grade: Optional[str] = Query(None, description="A/B/C/D/F"),
    sort: str = Query("score_desc", description="score_desc/score_asc"),
    db: AsyncSession = Depends(get_db)
):
    scores = await service.get_health_scores(db, grade=grade, sort=sort)
    return scores

@router.get("/health/scores/{account_id}", response_model=schemas.HealthScoreOut)
async def get_health_score_detail(
    account_id: int = Path(..., description="FB Account ID"),
    db: AsyncSession = Depends(get_db)
):
    item = await service.get_health_score_detail(db, account_id=account_id)
    if not item:
        raise HTTPException(status_code=404, detail="Health score not found")
    return item

@router.post("/health/recalculate", response_model=List[schemas.HealthScoreOut])
async def recalculate_all_health_scores(db: AsyncSession = Depends(get_db)):
    return await service.recalculate_all_health_scores(db)

@router.post("/health/recalculate/{account_id}", response_model=schemas.HealthScoreOut)
async def recalculate_health_score(
    account_id: int = Path(..., description="FB Account ID"),
    db: AsyncSession = Depends(get_db)
):
    item = await service.recalculate_account_health_score(db, account_id=account_id)
    if not item:
        raise HTTPException(status_code=404, detail="FB account not found")
    return item
