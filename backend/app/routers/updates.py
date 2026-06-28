from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_async_db
from app.models import TenderHistory

router = APIRouter(prefix="/api/v1/updates", tags=["updates"])

@router.get("/")
async def list_updates(limit: int = 50, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(TenderHistory)
        .order_by(desc(TenderHistory.changed_at))
        .limit(limit)
    )
    return result.scalars().all()
