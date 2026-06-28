from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_async_db
from app.models import TenderMatch

router = APIRouter(prefix="/api/v1/keyword-matches", tags=["keyword-matches"])

@router.get("/")
async def list_keyword_matches(limit: int = 50, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(TenderMatch)
        .order_by(desc(TenderMatch.created_at))
        .limit(limit)
    )
    return result.scalars().all()
