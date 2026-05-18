"""
FastAPI main application.

HR AI Agent Backend

This is the entry point for the FastAPI backend application.

To run:
    uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.core.config import settings
from backend.app.database.indexes import create_indexes
from backend.app.database.mongo_connection import MongoDB
from backend.app.database.redis_connection import RedisDB
from backend.app.routes.auth import router as auth_router
from backend.app.routes.master_data import router as master_data_router


# -------------------------
# Lifespan events
# -------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events.

    Startup:
    - Connect to MongoDB
    - Connect to Redis
    - Create database indexes

    Shutdown:
    - Disconnect from MongoDB
    - Disconnect from Redis
    """

    print("=" * 60)
    print("Starting HR AI Agent Backend")
    print("=" * 60)

    try:
        await MongoDB.connect()
        await RedisDB.connect()

        db = MongoDB.get_database()
        index_results = await create_indexes(db)

        print("=" * 60)
        print("All services started successfully")
        print("=" * 60)
        print(f"Environment: {settings.ENVIRONMENT}")
        print(f"Debug mode: {settings.DEBUG}")
        print(f"API prefix: {settings.API_PREFIX}")
        print(f"API documentation: http://localhost:{settings.PORT}/docs")
        print("Index summary:")
        for collection_name, result in index_results.items():
            total = result.get("total", 0) if isinstance(result, dict) else 0
            errors = result.get("errors", []) if isinstance(result, dict) else []
            print(
                f"  - {collection_name}: {total} indexes checked/created, "
                f"errors: {len(errors)}"
            )
        print("=" * 60)

    except Exception as exc:
        print("=" * 60)
        print(f"Failed to start services: {exc}")
        print("=" * 60)
        raise

    yield

    print("=" * 60)
    print("Shutting down HR AI Agent Backend")
    print("=" * 60)

    await RedisDB.disconnect()
    await MongoDB.disconnect()

    print("All services stopped")
    print("=" * 60)


# -------------------------
# FastAPI app
# -------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "HR AI Agent Backend\n\n"
        "Current modules:\n"
        "- Authentication with email OTP verification\n"
        "- Login with username/password\n"
        "- Forgot password with OTP\n"
        "- JWT access and refresh tokens\n"
        "- Role-based access control\n"
        "- Department master data management\n"
        "- Designation master data management\n"
        "- Leave type master data management\n"
        "- Claim type master data management\n"
        "- Holiday calendar master data management\n\n"
        "Master data capabilities:\n"
        "- Create, list, update, deactivate, and reactivate master records\n"
        "- Dropdown APIs for frontend forms\n"
        "- Bulk import APIs for Admin users\n"
        "- Statistics APIs for HR/Admin dashboards\n"
        "- Holiday calendar APIs for leave and payroll calculations\n\n"
        "Planned modules:\n"
        "- Employee profiles\n"
        "- Leave management\n"
        "- Claim/reimbursement workflows\n"
        "- Payroll queries\n"
        "- RAG-based HR policy Q&A\n"
        "- LangGraph AI agent workflows\n"
        "- Voice-based HR assistant\n"
    ),
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production() else None,
    redoc_url="/redoc" if not settings.is_production() else None,
    openapi_url="/openapi.json" if not settings.is_production() else None,
)


# -------------------------
# CORS middleware
# -------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=settings.ALLOW_CREDENTIALS,
    allow_methods=settings.get_cors_methods(),
    allow_headers=(
        settings.ALLOWED_HEADERS.split(",")
        if settings.ALLOWED_HEADERS != "*"
        else ["*"]
    ),
    expose_headers=["Content-Type", "Authorization"],
)


# -------------------------
# Route registration
# -------------------------

app.include_router(
    auth_router,
    prefix=settings.API_PREFIX,
)

app.include_router(
    master_data_router,
    prefix=settings.API_PREFIX,
)


# -------------------------
# Root endpoints
# -------------------------

@app.get(
    "/",
    tags=["Root"],
    summary="API root",
    description="Welcome endpoint with API information",
)
async def root():
    """
    Root endpoint.
    """

    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "environment": settings.ENVIRONMENT,
        "api_prefix": settings.API_PREFIX,
        "docs": "/docs" if not settings.is_production() else "disabled in production",
        "redoc": "/redoc" if not settings.is_production() else "disabled in production",
        "modules": [
            "authentication",
            "master_data_departments",
            "master_data_designations",
            "master_data_leave_types",
            "master_data_claim_types",
            "master_data_holidays",
        ],
        "planned_modules": [
            "employee_profiles",
            "leave_management",
            "claim_management",
            "payroll_queries",
            "policy_rag",
            "langgraph_ai_agent",
            "voice_assistant",
        ],
    }


@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Check if the service and its dependencies are healthy",
)
async def health_check():
    """
    Health check endpoint.

    Checks:
    - FastAPI service
    - MongoDB connection
    - Redis connection
    """

    health_status = {
        "service": "healthy",
        "mongodb": "unknown",
        "redis": "unknown",
        "environment": settings.ENVIRONMENT,
        "version": settings.APP_VERSION,
    }

    all_healthy = True

    try:
        client = MongoDB.get_client()
        await client.admin.command("ping")
        health_status["mongodb"] = "healthy"
    except Exception as exc:
        health_status["mongodb"] = f"unhealthy: {str(exc)}"
        all_healthy = False

    try:
        redis_client = RedisDB.get_client()
        await redis_client.ping()
        health_status["redis"] = "healthy"
    except Exception as exc:
        health_status["redis"] = f"unhealthy: {str(exc)}"
        all_healthy = False

    status_code = (
        status.HTTP_200_OK
        if all_healthy
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return JSONResponse(
        status_code=status_code,
        content=health_status,
    )


@app.get(
    "/health/ready",
    tags=["Health"],
    summary="Readiness check",
    description="Check if the service is ready to accept requests",
)
async def readiness_check():
    """
    Readiness check for Docker/Kubernetes health probes.
    """

    try:
        client = MongoDB.get_client()
        await client.admin.command("ping")

        redis_client = RedisDB.get_client()
        await redis_client.ping()

        return {
            "status": "ready",
            "service": settings.APP_NAME,
            "environment": settings.ENVIRONMENT,
        }

    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not ready",
                "error": str(exc),
            },
        )


@app.get(
    "/health/live",
    tags=["Health"],
    summary="Liveness check",
    description="Check if the service process is alive",
)
async def liveness_check():
    """
    Liveness check.

    If this endpoint responds, the service process is alive.
    """

    return {
        "status": "alive",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


# -------------------------
# Exception handlers
# -------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    """
    Handles Pydantic/FastAPI validation errors.
    """

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "error_code": "VALIDATION_ERROR",
            "path": request.url.path,
            "method": request.method,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc: Exception,
):
    """
    Handles unhandled exceptions.

    Production:
    - Return generic error

    Development:
    - Return detailed error
    """

    error_detail = str(exc)
    error_traceback = traceback.format_exc()

    print("=" * 60)
    print("UNHANDLED EXCEPTION")
    print("=" * 60)
    print(f"Path: {request.url.path}")
    print(f"Method: {request.method}")
    print(f"Error: {error_detail}")
    print("Traceback:")
    print(error_traceback)
    print("=" * 60)

    if settings.is_production():
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error. Please contact support.",
                "error_code": "INTERNAL_ERROR",
                "path": request.url.path,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": error_detail,
            "error_code": "INTERNAL_ERROR",
            "path": request.url.path,
            "method": request.method,
            "traceback": error_traceback.split("\n"),
        },
    )


# -------------------------
# Development server
# -------------------------

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("Starting development server")
    print("=" * 60)
    print(f"Host: {settings.HOST}")
    print(f"Port: {settings.PORT}")
    print(f"Reload: {settings.RELOAD}")
    print(f"Docs: http://localhost:{settings.PORT}/docs")
    print("=" * 60)

    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level="info",
    )