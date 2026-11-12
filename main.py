"""Main application entry point for PayWise Agent."""
import os
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.config import settings
from backend.database import init_db, get_db
from backend.schemas import HealthResponse
from backend.routers import (
    ai_routes,
    invoice_routes,
    dashboard_routes,
    payment_routes,
    reminder_routes
)

# Initialize database schema tables on startup
init_db()

app = FastAPI(
    title="PayWise Agent API",
    description="AI-Powered Invoice and Payment Assistant with Google Gemini AI and PayPal Sandbox integration.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(ai_routes.router)
app.include_router(invoice_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(payment_routes.router)
app.include_router(reminder_routes.router)


# Health check endpoint
@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Check system health, database connection, and API credentials status."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        version="1.0.0",
        gemini_configured=settings.is_gemini_configured,
        paypal_configured=settings.is_paypal_configured,
        paypal_environment=settings.PAYPAL_ENVIRONMENT,
        database_connected=db_ok
    )


# Settings endpoint to inspect configuration safely (without revealing raw secrets)
@app.get("/api/settings", tags=["Settings"])
def get_settings():
    """Retrieve configuration status safely with masked secret keys."""
    def mask_key(k: str | None) -> str:
        if not k or k.startswith("your_"):
            return "Not Configured"
        if len(k) <= 8:
            return "***"
        return f"{k[:4]}...{k[-4:]}"

    return {
        "gemini": {
            "configured": settings.is_gemini_configured,
            "model": settings.GEMINI_MODEL,
            "api_key_masked": mask_key(settings.GEMINI_API_KEY)
        },
        "paypal": {
            "configured": settings.is_paypal_configured,
            "environment": settings.PAYPAL_ENVIRONMENT,
            "client_id_masked": mask_key(settings.PAYPAL_CLIENT_ID),
            "client_secret_configured": bool(settings.PAYPAL_CLIENT_SECRET and not settings.PAYPAL_CLIENT_SECRET.startswith("your_")),
            "webhook_id_configured": bool(settings.PAYPAL_WEBHOOK_ID and not settings.PAYPAL_WEBHOOK_ID.startswith("your_"))
        },
        "server": {
            "host": settings.APP_HOST,
            "port": settings.APP_PORT,
            "database_url": "sqlite:///./paywise.db"
        }
    }


# Mount Frontend static files
frontend_path = settings.FRONTEND_DIR

if frontend_path.exists():
    # Serve static assets (CSS, JS)
    app.mount("/css", StaticFiles(directory=frontend_path / "css"), name="css")
    app.mount("/js", StaticFiles(directory=frontend_path / "js"), name="js")

    # Serve specific HTML pages
    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(frontend_path / "index.html")

    @app.get("/dashboard.html", include_in_schema=False)
    def serve_dashboard():
        return FileResponse(frontend_path / "dashboard.html")

    @app.get("/invoices.html", include_in_schema=False)
    def serve_invoices():
        return FileResponse(frontend_path / "invoices.html")

    @app.get("/invoice-detail.html", include_in_schema=False)
    def serve_invoice_detail():
        return FileResponse(frontend_path / "invoice-detail.html")

    @app.get("/reminders.html", include_in_schema=False)
    def serve_reminders():
        return FileResponse(frontend_path / "reminders.html")

    @app.get("/settings.html", include_in_schema=False)
    def serve_settings():
        return FileResponse(frontend_path / "settings.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=settings.DEBUG)
