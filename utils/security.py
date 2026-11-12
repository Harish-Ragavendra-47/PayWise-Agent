"""Security, currency validation, and webhook verification utilities."""
from typing import Dict, Any, Tuple
import re

# Standard currencies supported by PayPal REST Invoicing
# Note: PayPal Sandbox accounts in US/global default to USD, EUR, GBP, CAD, AUD, JPY etc.
# INR has special local regulations in PayPal and is often restricted or unsupported for non-Indian accounts or invoice API.
SUPPORTED_PAYPAL_CURRENCIES = {
    "USD": "United States Dollar",
    "EUR": "Euro",
    "GBP": "British Pound Sterling",
    "CAD": "Canadian Dollar",
    "AUD": "Australian Dollar",
    "JPY": "Japanese Yen",
    "SGD": "Singapore Dollar",
    "CHF": "Swiss Franc",
    "NZD": "New Zealand Dollar",
}


def validate_currency_support(currency: str) -> Tuple[bool, str]:
    """
    Validate whether the currency is supported by PayPal Invoicing Sandbox.
    Enforces Rule 7: Never silently convert currencies (e.g. INR to USD).
    """
    norm = currency.upper().strip()
    if norm in SUPPORTED_PAYPAL_CURRENCIES:
        return True, f"{norm} ({SUPPORTED_PAYPAL_CURRENCIES[norm]}) is supported."
    
    if norm == "INR":
        return False, (
            "Indian Rupee (INR) is not directly supported for standard cross-border PayPal Sandbox invoices. "
            "Please select a supported currency like USD, EUR, or GBP. We will never silently convert your amount."
        )
    
    return False, f"Currency '{norm}' is not supported by the current PayPal Sandbox configuration. Supported: {', '.join(SUPPORTED_PAYPAL_CURRENCIES.keys())}."


def sanitize_text(text: str) -> str:
    """Sanitize user text input against harmful injections and strip excessive whitespace."""
    if not text:
        return ""
    # Strip script/html tags
    clean = re.sub(r"<[^>]*>", "", text)
    return clean.strip()
