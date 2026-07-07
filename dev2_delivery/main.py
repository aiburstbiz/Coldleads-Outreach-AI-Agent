from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dev2_delivery.routes.approval import router as approval_router
from dev2_delivery.database import engine
import dev2_delivery.db_models  # noqa: F401


# lifespan must be defined BEFORE app = FastAPI(...)
@asynccontextmanager
async def lifespan(app: FastAPI):
    dev2_delivery.db_models.Base.metadata.create_all(bind=engine)
    yield


# then pass it in here
app = FastAPI(title="AI Sales Agent - Content & Delivery", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(approval_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}