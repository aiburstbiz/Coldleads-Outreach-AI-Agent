from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dev2_delivery.routes.approval import router as approval_router

app = FastAPI(title="AI Sales Agent - Content & Delivery")

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