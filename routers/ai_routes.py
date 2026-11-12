"""AI extraction and smart assistance API routes."""
from fastapi import APIRouter, HTTPException, status
from backend.schemas import AIExtractRequest, AIExtractResponse
from backend.services.ai_service import extract_invoice_details
from backend.config import settings

router = APIRouter(prefix="/api/ai", tags=["AI Agent"])


@router.post("/extract-invoice", response_model=AIExtractResponse)
def api_extract_invoice(request: AIExtractRequest):
    """
    Extract structured invoice data from natural language user prompt using Google Gemini AI.
    Returns clear errors if GEMINI_API_KEY is not configured.
    """
    if not settings.is_gemini_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Gemini API key is not configured. Please add your GEMINI_API_KEY in the .env file "
                "or update it via the Settings page. You can still create and manage invoices manually!"
            )
        )

    try:
        extracted = extract_invoice_details(request.user_prompt)
        return AIExtractResponse(
            success=True,
            client_name=extracted.get("client_name"),
            client_email=extracted.get("client_email"),
            description=extracted.get("description"),
            quantity=extracted.get("quantity", 1),
            unit_price=extracted.get("unit_price"),
            total_amount=extracted.get("total_amount"),
            currency=extracted.get("currency", "USD"),
            issue_date=extracted.get("issue_date"),
            due_date=extracted.get("due_date"),
            missing_fields=extracted.get("missing_fields", []),
            confidence_notes=extracted.get("notes"),
            raw_prompt=request.user_prompt
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"AI extraction error: {str(exc)}")
