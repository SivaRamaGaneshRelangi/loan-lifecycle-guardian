import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from .routers import admin, agent, auth, customer, officer
from .seed import seed
from .services.autopay import run_autopay
from .services.lifecycle import BusinessError

logging.basicConfig(level=logging.INFO)
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


async def _scheduler():
    while True:
        await asyncio.sleep(settings.AUTOPAY_SCHEDULER_SECONDS)
        db = SessionLocal()
        try:
            res = await asyncio.to_thread(run_autopay, db)
            logging.info("autopay run: %d items", len(res))
        except Exception:  # noqa: BLE001
            logging.exception("autopay scheduler failed")
        finally:
            db.close()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.DEMO_MODE:
       s = settings.JWT_SECRET
       if s.startswith(("dev-secret", "replace-this-placeholder")) or len(s) < 32:
           raise RuntimeError("Set a real JWT_SECRET (32+ random characters) before DEMO_MODE=0")
    Base.metadata.create_all(engine)
    if settings.SEED_DEMO:
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()
    task = asyncio.create_task(_scheduler()) if settings.AUTOPAY_SCHEDULER_SECONDS > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Loan Lifecycle Guardian", lifespan=lifespan)


@app.exception_handler(BusinessError)
async def business_error(_: Request, exc: BusinessError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


for r in (auth.router, customer.router, officer.router, admin.router, agent.router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
def health():
    from .services import llm
    return {"status": "ok", "llm_configured": llm.available(), "model": settings.GEMINI_MODEL}
