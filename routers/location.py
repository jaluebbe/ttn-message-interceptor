import os

from fastapi import APIRouter, HTTPException, Response
from redis import asyncio as aioredis

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")

router = APIRouter()


@router.get("/api/location")
async def get_location():
    async with aioredis.Redis(
        host=REDIS_HOST, decode_responses=True
    ) as redis_connection:
        _data = await redis_connection.get("gps_latest")
        if not _data:
            raise HTTPException(status_code=404, detail="no data available")
        return Response(content=_data, media_type="application/json")
