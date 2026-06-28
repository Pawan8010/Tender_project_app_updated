from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_async_db
from app.models import TenderChangeEvent

router = APIRouter(prefix="/api/v1/changes", tags=["changes"])

@router.get("/")
async def list_changes(limit: int = 50, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(TenderChangeEvent)
        .order_by(desc(TenderChangeEvent.detected_at))
        .limit(limit)
    )
    return result.scalars().all()
