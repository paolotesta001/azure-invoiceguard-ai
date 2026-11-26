"""Payment gateway: marks an invoice as approved for payment in the (mock) ERP.

Only the backend calls this, after a coded policy decision or a human decision.
The LLM never gets access to it. Signed approval tokens are added in v4.
"""

import threading
from typing import Protocol

import httpx

from invoiceguard.adapters.retry import TransientError


class PaymentGatewayError(Exception):
    """Permanent failure from the payment gateway (4xx other than 429)."""


class PaymentGateway(Protocol):
    def approve_payment(self, invoice_id: str, approved_by: str) -> str: ...


class InMemoryPaymentGateway:
    """In-process gateway for tests and the no-Docker demo. Idempotent per invoice."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.approvals: dict[str, tuple[str, str]] = {}

    def approve_payment(self, invoice_id: str, approved_by: str) -> str:
        with self._lock:
            if invoice_id not in self.approvals:
                self.approvals[invoice_id] = (f"PAY-{len(self.approvals) + 1:06d}", approved_by)
            return self.approvals[invoice_id][0]


class HttpPaymentGateway:
    """Calls ``POST /payments/approvals`` on the mock ERP."""

    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=10.0)

    def approve_payment(self, invoice_id: str, approved_by: str) -> str:
        try:
            response = self._client.post(
                "/payments/approvals", json={"invoice_id": invoice_id, "approved_by": approved_by}
            )
        except httpx.TransportError as exc:
            raise TransientError(f"ERP unreachable: {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("retry-after")
            raise TransientError(
                f"ERP returned {response.status_code}",
                retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code >= 400:
            raise PaymentGatewayError(f"ERP rejected approval: {response.status_code}")
        return str(response.json()["approval_reference"])
