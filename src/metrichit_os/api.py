from fastapi import APIRouter, FastAPI

from .models import (
    ContextResponse,
    EditorialStatusResponse,
    HealthResponse,
    MemorySummaryResponse,
)
from .services import current_context, editorial_status, memory_summary


router = APIRouter(prefix="/api/v1")


@router.get("/context", response_model=ContextResponse)
def get_context() -> dict[str, object]:
    return current_context()


@router.get("/memory/summary", response_model=MemorySummaryResponse)
def get_memory_summary() -> dict[str, object]:
    return memory_summary()


@router.get("/editorial/status", response_model=EditorialStatusResponse)
def get_editorial_status() -> dict[str, object]:
    return editorial_status()


app = FastAPI(
    title="MetricHit OS",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


app.include_router(router)
