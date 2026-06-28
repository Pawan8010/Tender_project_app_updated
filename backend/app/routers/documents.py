from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_async_db
from app.models import DocumentDownload

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

@router.get("/")
async def list_documents(limit: int = 50, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(DocumentDownload)
        .order_by(desc(DocumentDownload.id))
        .limit(limit)
    )
    return result.scalars().all()
