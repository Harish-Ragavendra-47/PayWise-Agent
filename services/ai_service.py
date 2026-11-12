"""Google Gemini AI service for structured invoice extraction and smart reminders."""
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types

from backend.config import settings


def extract_invoice_details(user_prompt: str) -> Dict[str, Any]:
    """
    Extract structured invoice fields from natural language text using Gemini.
    
    Requirements:
    1. Receive natural-language input.
    2. Send input to Gemini using configured GEMINI_MODEL.
    3. Request structured JSON output.
    4. Validate the response.
    5. Return extracted invoice information.
    6. Handle missing information.
    7. Never invent a client email or financial amount.
    8. Return clear validation errors if API key is missing.
    """
    if not settings.is_gemini_configured:
        raise ValueError(
            "Gemini API key is not configured. Please provide GEMINI_API_KEY in your .env file "
            "or configure it in Settings to enable AI invoice extraction."
        )

    today_str = date.today().isoformat()

    system_prompt = (
        f"You are an expert AI invoice parsing assistant for PayWise Agent. Today's date is {today_str}.\n"
        "Your task is to parse natural-language billing requests and extract structured invoice information.\n"
        "\nCRITICAL RULES:\n"
        "1. Return ONLY a valid JSON object. Do not include markdown code fence formatting or conversational text.\n"
        "2. NEVER invent or hallucinate client email, phone numbers, or monetary amounts. If not explicitly specified, set them to null and list them in 'missing_fields'.\n"
        "3. If a relative due date is stated (e.g. 'due in 7 days', 'due tomorrow', 'due next Friday'), calculate the exact date in YYYY-MM-DD format based on today's date.\n"
        "4. Standardize currency to a 3-letter ISO code (e.g., USD, EUR, GBP, INR, CAD). If currency is omitted or ambiguous ($ symbol), default to USD and note it.\n"
        "5. Financial amounts must be numeric strings formatted with two decimal places (e.g. '5000.00').\n"
        "6. Identify any missing required fields: 'client_name', 'client_email', 'description', 'unit_price', 'due_date'.\n"
        "\nRequired JSON schema:\n"
        "{\n"
        '  "client_name": string or null,\n'
        '  "client_email": string or null,\n'
        '  "description": string or null,\n'
        '  "quantity": number (default 1.0),\n'
        '  "unit_price": string or null,\n'
        '  "currency": string,\n'
        '  "due_date": "YYYY-MM-DD" or null,\n'
        '  "missing_fields": [string],\n'
        '  "notes": string or null\n'
        "}"
    )

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1000,
            )
        )
    except Exception as e:
        raise RuntimeError(f"Gemini API request failed: {str(e)}")

    content = response.text.strip() if response.text else ""

    # Extract JSON content if wrapped in markdown code blocks
    json_match = re.search(r"(\{.*\})", content, re.DOTALL)
    if json_match:
        content = json_match.group(1)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as err:
        raise ValueError(f"Failed to parse Gemini output as JSON: {err}. Raw response: {content[:200]}")

    # Validate and standardize fields
    missing_fields = list(data.get("missing_fields", []))

    client_name = data.get("client_name")
    if not client_name:
        if "client_name" not in missing_fields:
            missing_fields.append("client_name")

    client_email = data.get("client_email")
    if not client_email:
        if "client_email" not in missing_fields:
            missing_fields.append("client_email")

    description = data.get("description")
    if not description:
        if "description" not in missing_fields:
            missing_fields.append("description")

    # Unit price & total calculation
    unit_price_val = data.get("unit_price")
    unit_price = None
    if unit_price_val is not None:
        try:
            unit_price = Decimal(str(unit_price_val)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            unit_price = None
            if "unit_price" not in missing_fields:
                missing_fields.append("unit_price")
    else:
        if "unit_price" not in missing_fields:
            missing_fields.append("unit_price")

    quantity_val = data.get("quantity", 1)
    try:
        quantity = Decimal(str(quantity_val))
        if quantity <= Decimal("0"):
            quantity = Decimal("1.00")
    except (InvalidOperation, ValueError):
        quantity = Decimal("1.00")

    currency = str(data.get("currency", "USD")).upper().strip()

    # Due date parsing
    due_date_str = data.get("due_date")
    parsed_due_date = None
    if due_date_str:
        try:
            parsed_due_date = date.fromisoformat(due_date_str)
        except ValueError:
            parsed_due_date = date.today() + timedelta(days=7)
    else:
        # Default to 7 days if not detected, but mark as missing so user can review
        parsed_due_date = date.today() + timedelta(days=7)
        if "due_date" not in missing_fields:
            missing_fields.append("due_date")

    total_amount = (unit_price * quantity) if unit_price is not None else None

    return {
        "client_name": client_name,
        "client_email": client_email,
        "description": description,
        "quantity": float(quantity),
        "unit_price": str(unit_price) if unit_price is not None else None,
        "total_amount": str(total_amount) if total_amount is not None else None,
        "currency": currency,
        "issue_date": today_str,
        "due_date": parsed_due_date.isoformat() if parsed_due_date else None,
        "missing_fields": missing_fields,
        "notes": data.get("notes")
    }


def generate_reminder_text_ai(
    client_name: str,
    invoice_number: str,
    amount: Decimal,
    currency: str,
    due_date: str,
    tone: str = "professional"
) -> str:
    """Generate an AI-drafted payment reminder using Gemini, or a high-quality fallback template."""
    valid_tones = ["friendly", "professional", "urgent"]
    selected_tone = tone.lower().strip()
    if selected_tone not in valid_tones:
        selected_tone = "professional"

    if settings.is_gemini_configured:
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            prompt = (
                f"Draft a payment reminder email/message for a freelance invoice.\n"
                f"- Client Name: {client_name}\n"
                f"- Invoice Number: {invoice_number}\n"
                f"- Amount Due: {amount} {currency}\n"
                f"- Due Date: {due_date}\n"
                f"- Tone: {selected_tone} (Tone options: friendly, professional, urgent but polite)\n\n"
                "Keep it concise, clear, and ready to send. Return only the reminder text without greetings to the AI or markdown code fences."
            )
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=350,
                )
            )
            if response.text:
                return response.text.strip()
        except Exception:
            # Fall back to templated generator if API call fails
            pass

    # Template-based fallback
    if selected_tone == "friendly":
        return (
            f"Hi {client_name},\n\n"
            f"Hope you are having a wonderful week! This is a friendly reminder that invoice {invoice_number} "
            f"for {amount} {currency} is scheduled for payment by {due_date}.\n\n"
            f"Please let me know if you need any additional details. Thank you so much for your business!\n\n"
            f"Best regards,\nPayWise Agent"
        )
    elif selected_tone == "urgent":
        return (
            f"Dear {client_name},\n\n"
            f"URGENT: Invoice {invoice_number} for {amount} {currency} was due on {due_date} and is currently outstanding.\n\n"
            f"Kindly arrange for immediate settlement via the PayPal payment link to ensure uninterrupted service.\n"
            f"If you have already processed this payment, please disregard this note.\n\n"
            f"Sincerely,\nPayWise Agent"
        )
    else:  # professional
        return (
            f"Dear {client_name},\n\n"
            f"This is a reminder that invoice {invoice_number} in the amount of {amount} {currency} "
            f"is due on {due_date}.\n\n"
            f"You can review and pay the invoice directly through the secure PayPal link provided.\n"
            f"Thank you for your prompt attention to this matter.\n\n"
            f"Warm regards,\nPayWise Agent"
        )
