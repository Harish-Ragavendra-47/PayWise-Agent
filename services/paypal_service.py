"""PayPal REST Invoicing API Service for PayWise Agent."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
import httpx

from backend.config import settings
from backend.utils.security import validate_currency_support


class PayPalError(Exception):
    """Base exception for PayPal operations."""
    pass


class PayPalCredentialsMissingError(PayPalError):
    """Raised when PayPal Client ID or Secret are not configured."""
    pass


class PayPalService:
    """Manages PayPal Sandbox OAuth 2.0 and Invoicing v2 API interactions."""

    def __init__(self):
        self._cached_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    def _ensure_credentials(self):
        if not settings.is_paypal_configured:
            raise PayPalCredentialsMissingError(
                "PayPal API credentials are not configured or are set to placeholder values. "
                "Please add PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET to your .env file "
                "or update them in the Settings page."
            )

    def get_access_token(self) -> str:
        """
        Obtain OAuth 2.0 access token via Client Credentials Grant.
        Caches the token until near expiration.
        """
        self._ensure_credentials()

        now = datetime.utcnow()
        if self._cached_token and self._token_expires_at and now < self._token_expires_at:
            return self._cached_token

        url = f"{settings.paypal_base_url}/v1/oauth2/token"
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    url,
                    auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                    data={"grant_type": "client_credentials"},
                    headers={
                        "Accept": "application/json",
                        "Accept-Language": "en_US"
                    }
                )
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error connecting to PayPal OAuth: {str(exc)}")

        if response.status_code != 200:
            error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = error_data.get("error_description") or error_data.get("message") or response.text
            raise PayPalError(f"PayPal OAuth authorization failed ({response.status_code}): {err_msg}")

        data = response.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))

        if not token:
            raise PayPalError("PayPal OAuth response did not contain an access_token.")

        self._cached_token = token
        # Buffer expiration by 60 seconds
        self._token_expires_at = now + timedelta(seconds=max(expires_in - 60, 60))
        return self._cached_token

    def _auth_headers(self) -> Dict[str, str]:
        token = self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation"
        }

    def create_invoice(
        self,
        invoice_number: str,
        client_name: str,
        client_email: Optional[str],
        description: str,
        quantity: Decimal,
        unit_price: Decimal,
        currency: str,
        issue_date: str,
        due_date: str,
    ) -> Dict[str, Any]:
        """
        Create a draft invoice in PayPal Sandbox Invoicing v2.
        Follows official PayPal Invoicing v2 API specifications.
        """
        self._ensure_credentials()

        is_supported, reason = validate_currency_support(currency)
        if not is_supported:
            raise PayPalError(reason)

        url = f"{settings.paypal_base_url}/v2/invoicing/invoices"

        # Split client name into given_name and surname for PayPal recipient schema
        name_parts = client_name.strip().split(" ", 1)
        given_name = name_parts[0]
        surname = name_parts[1] if len(name_parts) > 1 else ""

        billing_info: Dict[str, Any] = {
            "name": {
                "given_name": given_name,
            }
        }
        if surname:
            billing_info["name"]["surname"] = surname
        if client_email:
            billing_info["email_address"] = client_email

        payload: Dict[str, Any] = {
            "detail": {
                "invoice_number": invoice_number,
                "invoice_date": issue_date,
                "currency_code": currency.upper(),
                "payment_term": {
                    "term_type": "DUE_ON_DATE",
                    "due_date": due_date
                },
                "note": "Thank you for your business! Generated via PayWise Agent."
            },
            "primary_recipients": [
                {
                    "billing_info": billing_info
                }
            ],
            "items": [
                {
                    "name": description[:100],
                    "description": description,
                    "quantity": str(quantity),
                    "unit_amount": {
                        "currency_code": currency.upper(),
                        "value": f"{unit_price:.2f}"
                    },
                    "unit_of_measure": "QUANTITY"
                }
            ]
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(url, json=payload, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error creating invoice on PayPal: {str(exc)}")

        if response.status_code not in (200, 201):
            err_detail = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            details = err_detail.get("details", [])
            msg = err_detail.get("message") or response.text
            if details:
                detail_msgs = "; ".join([d.get("description", "") for d in details if d.get("description")])
                if detail_msgs:
                    msg = f"{msg}: {detail_msgs}"
            raise PayPalError(f"PayPal invoice creation failed ({response.status_code}): {msg}")

        data = response.json()
        paypal_id = data.get("id")
        
        # Extract hosted URL if available from links
        hosted_url = None
        for link in data.get("links", []):
            if link.get("rel") == "payer-view":
                hosted_url = link.get("href")
                break

        return {
            "paypal_invoice_id": paypal_id,
            "status": data.get("status", "DRAFT"),
            "paypal_invoice_url": hosted_url,
            "raw": data
        }

    def send_invoice(self, paypal_invoice_id: str) -> Dict[str, Any]:
        """
        Send invoice via PayPal Invoicing API.
        Sends email notification to client through PayPal and provides hosted URL.
        """
        self._ensure_credentials()

        url = f"{settings.paypal_base_url}/v2/invoicing/invoices/{paypal_invoice_id}/send"
        payload = {
            "send_to_recipient": True,
            "send_to_invoicer": False
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(url, json=payload, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error sending invoice via PayPal: {str(exc)}")

        if response.status_code not in (200, 202):
            err = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise PayPalError(f"PayPal send invoice failed ({response.status_code}): {err.get('message', response.text)}")

        # Fetch the updated invoice to get the actual payer-view hosted link
        return self.get_invoice_details(paypal_invoice_id)

    def get_invoice_details(self, paypal_invoice_id: str) -> Dict[str, Any]:
        """Retrieve real-time invoice details and payment status from PayPal."""
        self._ensure_credentials()

        url = f"{settings.paypal_base_url}/v2/invoicing/invoices/{paypal_invoice_id}"
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(url, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error fetching PayPal invoice details: {str(exc)}")

        if response.status_code != 200:
            err = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise PayPalError(f"PayPal invoice lookup failed ({response.status_code}): {err.get('message', response.text)}")

        data = response.json()
        status = data.get("status", "UNKNOWN")

        # Map PayPal invoice status to our application statuses
        # PayPal statuses: DRAFT, SENT, SCHEDULED, PAID, MARKED_AS_PAID, CANCELLED, REFUNDED, PARTIALLY_PAID, PAYMENT_PENDING
        normalized_status = status
        if status in ("PAID", "MARKED_AS_PAID"):
            normalized_status = "PAID"
        elif status in ("SENT", "SCHEDULED"):
            normalized_status = "SENT"
        elif status == "CANCELLED":
            normalized_status = "CANCELLED"
        elif status == "DRAFT":
            normalized_status = "DRAFT"

        hosted_url = None
        for link in data.get("links", []):
            if link.get("rel") == "payer-view":
                hosted_url = link.get("href")
                break

        # Check for recorded payments in PayPal
        payments_data = data.get("payments", {}).get("transactions", [])
        total_paid = Decimal("0.00")
        for tx in payments_data:
            amount_val = tx.get("amount", {}).get("value")
            if amount_val:
                total_paid += Decimal(str(amount_val))

        return {
            "paypal_invoice_id": paypal_invoice_id,
            "status": normalized_status,
            "raw_paypal_status": status,
            "paypal_invoice_url": hosted_url,
            "total_paid": total_paid,
            "transactions": payments_data,
            "raw": data
        }

    def cancel_invoice(self, paypal_invoice_id: str, note: str = "Cancelled by merchant via PayWise Agent") -> Dict[str, Any]:
        """Cancel an invoice in PayPal if supported for its current state."""
        self._ensure_credentials()

        url = f"{settings.paypal_base_url}/v2/invoicing/invoices/{paypal_invoice_id}/cancel"
        payload = {
            "subject": "Invoice Cancelled",
            "note": note,
            "send_to_invoicer": False,
            "send_to_recipient": True
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, json=payload, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error cancelling PayPal invoice: {str(exc)}")

        if response.status_code not in (200, 204):
            err = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise PayPalError(f"PayPal cancel failed ({response.status_code}): {err.get('message', response.text)}")

        return {"status": "CANCELLED", "paypal_invoice_id": paypal_invoice_id}

    def verify_webhook_signature(
        self,
        headers: Dict[str, str],
        webhook_body: Dict[str, Any]
    ) -> bool:
        """
        Verify incoming PayPal webhook signature using PayPal's official API endpoint.
        Returns True if verified authentic by PayPal, False otherwise.
        """
        if not settings.is_paypal_configured or not settings.PAYPAL_WEBHOOK_ID:
            return False

        # Extract required PayPal signature headers
        auth_algo = headers.get("paypal-auth-algo") or headers.get("PAYPAL-AUTH-ALGO")
        cert_url = headers.get("paypal-cert-url") or headers.get("PAYPAL-CERT-URL")
        transmission_id = headers.get("paypal-transmission-id") or headers.get("PAYPAL-TRANSMISSION-ID")
        transmission_sig = headers.get("paypal-transmission-sig") or headers.get("PAYPAL-TRANSMISSION-SIG")
        transmission_time = headers.get("paypal-transmission-time") or headers.get("PAYPAL-TRANSMISSION-TIME")

        if not all([auth_algo, cert_url, transmission_id, transmission_sig, transmission_time]):
            return False

        verify_payload = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": settings.PAYPAL_WEBHOOK_ID,
            "webhook_event": webhook_body
        }

        url = f"{settings.paypal_base_url}/v1/notifications/verify-webhook-signature"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, json=verify_payload, headers=self._auth_headers())
                if res.status_code == 200:
                    data = res.json()
                    return data.get("verification_status") == "SUCCESS"
        except Exception:
            return False

        return False


paypal_service = PayPalService()
