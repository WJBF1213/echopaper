"""GET /api/health"""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    return {"ok": True, "version": request.app.version}
