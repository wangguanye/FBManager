from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from datetime import datetime
import csv
import io
from db.database import get_db
from modules.ad import service, schemas

router = APIRouter(tags=["Ads"])

@router.get("/bm", response_model=List[schemas.BMOut])
async def list_bm(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return await service.get_bm_list(db, status)

@router.post("/bm", response_model=schemas.BMOut)
async def create_bm(payload: schemas.BMCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_bm(db, payload)

@router.patch("/bm/{id}", response_model=schemas.BMOut)
async def update_bm(id: int, payload: schemas.BMUpdate, db: AsyncSession = Depends(get_db)):
    bm = await service.update_bm(db, id, payload)
    if not bm:
        raise HTTPException(status_code=404, detail="BM not found")
    return bm

@router.delete("/bm/{id}")
async def delete_bm(id: int, db: AsyncSession = Depends(get_db)):
    result = await service.delete_bm(db, id)
    if result is None:
        raise HTTPException(status_code=404, detail="BM not found")
    return {"code": 0, "msg": "Deleted successfully"}

@router.get("/ad-accounts", response_model=List[schemas.AdAccountOut])
async def list_ad_accounts(
    bm_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    return await service.get_ad_accounts(db, bm_id=bm_id, status=status)

@router.post("/ad-accounts", response_model=schemas.AdAccountOut)
async def create_ad_account(payload: schemas.AdAccountCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_ad_account(db, payload)

@router.patch("/ad-accounts/{id}", response_model=Dict[str, Any])
async def update_ad_account(id: int, payload: schemas.AdAccountUpdate, db: AsyncSession = Depends(get_db)):
    result = await service.update_ad_account(db, id, payload)
    if not result:
        raise HTTPException(status_code=404, detail="Ad account not found")
    account_payload = schemas.AdAccountOut.model_validate(result["data"]).model_dump()
    return {"data": account_payload, "warnings": result["warnings"]}

@router.get("/ad-accounts/{id}/detail", response_model=Dict[str, Any])
async def ad_account_detail(id: int, db: AsyncSession = Depends(get_db)):
    detail = await service.get_ad_account_detail(db, id)
    if not detail:
        raise HTTPException(status_code=404, detail="Ad account not found")
    account_payload = schemas.AdAccountOut.model_validate(detail["account"]).model_dump()
    bm_payload = schemas.BMOut.model_validate(detail["bm"]).model_dump() if detail["bm"] else None
    stats_payload = [schemas.AdDailyStatOut.model_validate(item).model_dump() for item in detail["recent_stats"]]
    budget_payload = [schemas.BudgetChangeOut.model_validate(item).model_dump() for item in detail["budget_changes"]]
    return {
        "account": account_payload,
        "bm": bm_payload,
        "recent_stats": stats_payload,
        "budget_changes": budget_payload,
    }

@router.get("/fanpages", response_model=List[schemas.FanpageOut])
async def list_fanpages(fb_account_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    return await service.get_fanpages(db, fb_account_id=fb_account_id)

@router.post("/fanpages", response_model=schemas.FanpageOut)
async def create_fanpage(payload: schemas.FanpageCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_fanpage(db, payload)

@router.patch("/fanpages/{id}", response_model=schemas.FanpageOut)
async def update_fanpage(id: int, payload: schemas.FanpageUpdate, db: AsyncSession = Depends(get_db)):
    fanpage = await service.update_fanpage(db, id, payload)
    if not fanpage:
        raise HTTPException(status_code=404, detail="Fanpage not found")
    return fanpage

@router.post("/ad-stats", response_model=schemas.AdDailyStatOut)
async def upsert_ad_stat(payload: schemas.AdDailyStatCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_or_update_stat(db, payload)

@router.get("/ad-stats", response_model=List[schemas.AdDailyStatOut])
async def list_ad_stats(
    ad_account_id: int = Query(...),
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    return await service.get_stats(db, ad_account_id, date_start, date_end)

@router.get("/ad-stats/summary", response_model=Dict[str, Any])
async def ad_stats_summary(ad_account_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    return await service.get_stats_summary(db, ad_account_id)

@router.get("/ad-stats/export")
async def export_ad_stats(
    ad_account_id: int = Query(...),
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Unsupported format")
    stats = await service.get_stats(db, ad_account_id, date_start, date_end)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["日期", "广告账户ID", "消耗($)", "展示", "点击", "转化", "CPM($)", "CPC($)", "CTR(%)", "CVR(%)", "ROAS", "CPP($)"])
    for item in stats:
        writer.writerow([
            item.date.strftime("%Y-%m-%d") if item.date else "",
            item.ad_account_id,
            f"{item.spend / 100:.2f}",
            item.impressions,
            item.clicks,
            item.conversions,
            f"{item.cpm / 100:.2f}",
            f"{item.cpc / 100:.2f}",
            f"{item.ctr:.2f}",
            f"{item.cvr:.2f}",
            f"{item.roas:.2f}",
            f"{item.cpp / 100:.2f}"
        ])
    output.seek(0)
    filename = f"ad_stats_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/budget-changes", response_model=List[schemas.BudgetChangeOut])
async def budget_changes(ad_account_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    return await service.get_budget_history(db, ad_account_id)

@router.get("/ad-overview", response_model=Dict[str, Any])
async def ad_overview(db: AsyncSession = Depends(get_db)):
    return await service.get_ad_overview(db)
