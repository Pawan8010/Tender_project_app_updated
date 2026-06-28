from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_async_db
from app.models import WorkerStatus

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])

@router.get("/")
async def list_workers(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(WorkerStatus))
    return result.scalars().all()
