import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings, validate_production_security
import asyncio
import logging
import db
from app.database.session import init_db
from app.database.seed import seed_database
from app.api.webhook import router as webhook_router
from app.api.simulator import router as simulator_router

logger = logging.getLogger(__name__)


async def session_cleanup_task():
    """Periodic background task to prune expired conversation turns every hour."""
    while True:
        try:
            await asyncio.sleep(3600)  # Runs every hour
            cleaned = db.cleanup_expired_sessions(ttl_minutes=120)
            if cleaned > 0:
                logger.info(f"[Maintenance] Cleaned {cleaned} expired conversation turns.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Maintenance Error] Session cleanup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enforce fail-closed security check for production
    validate_production_security(settings)

    # Initialize SQLModel & raw DB schemas & default seed data
    init_db()
    seed_database()
    db.init_db()
    db.seed_default_data()
    print("Database initialized and seeded.")

    # Start background tasks: Durable message job queue + periodic session cleanup
    from job_queue import job_queue
    queue_worker = asyncio.create_task(job_queue.run_worker_loop())
    cleanup_worker = asyncio.create_task(session_cleanup_task())
    try:
        yield
    finally:
        job_queue.stop_worker()
        queue_worker.cancel()
        cleanup_worker.cancel()
        try:
            await queue_worker
        except asyncio.CancelledError:
            pass
        try:
            await cleanup_worker
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="نظام الاستقبال والاستفسار الذكي لمصحة طبية عبر واتساب",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: explicit origins only, credentials never allowed, and only the
# methods/headers this app actually uses. Previously every origin, method,
# and header was allowed, which exposed the simulator state and admin
# endpoints to any website a staff member happened to visit.
_cors_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Key", "X-Hub-Signature-256", "Accept"],
)

# Include Routers
from router import router as core_whatsapp_router
app.include_router(core_whatsapp_router)
app.include_router(webhook_router)
app.include_router(simulator_router)

# Mount Static Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "LibyAI Clinic Reception System API is running."}


@app.get("/health")
async def health_check():
    return {"status": "ok", "clinic": settings.CLINIC_NAME}
