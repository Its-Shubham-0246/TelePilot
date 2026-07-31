from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import admin, payments
from core.database import init_db

app = FastAPI(
    title="Telegram Multi-Account SaaS Automation API",
    version="1.0.0",
    description="Backend API engine managing user subscriptions, session security, and webhook callbacks."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(payments.router)


@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Telegram SaaS Backend"}
