from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_async_db
from app.models import ScrapeLog, SystemLog

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])

@router.get("/")
async def list_logs(limit: int = 100, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(ScrapeLog)
        .order_by(desc(ScrapeLog.scraped_at))
        .limit(limit)
    )
    return result.scalars().all()

@router.get("/system")
async def list_system_logs(limit: int = 100, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(SystemLog)
        .order_by(desc(SystemLog.created_at))
        .limit(limit)
    )
    return result.scalars().all()
