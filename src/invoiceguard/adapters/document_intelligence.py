"""Document Intelligence adapters (``prebuilt-invoice`` + query fields).

* ``DocumentIntelligenceAnalyzer`` – real service, Microsoft Entra ID auth
  (package ``azure-ai-documentintelligence`` 1.0.x → API 2024-11-30; needs a single-service
  resource for Entra ID). Imported lazily so mock mode never needs the Azure SDK.
* ``RecordedAnalyzer`` – replays JSON results stored under ``<recordings>/document_intelligence/
  <sha256>.json``. Used in mock mode and tests. Recordings are either *simulated* (generated
  from the synthetic ground truth) or *live* (saved by ``scripts/record_responses.py``).

UNVERIFIED (see docs/sdk-notes.md): the exact keyword names for query fields
(``features=[DocumentAnalysisFeature.QUERY_FIELDS]``, ``query_fields=[...]``) and the use of
``AnalyzeResult.as_dict()`` to get the REST-shaped JSON. Both are isolated in ``_analyze``.
"""

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from invoiceguard.adapters.retry import TransientError, call_with_retry
from invoiceguard.ingestion.di_mapping import QUERY_FIELDS
from invoiceguard.ingestion.errors import ExtractionError

MODEL_ID = "prebuilt-invoice"


class InvoiceAnalyzer(Protocol):
    source_label: str

    def analyze_invoice(self, content: bytes) -> dict[str, Any]: ...


class RecordedAnalyzer:
    """Replays recorded analyze results keyed by the SHA-256 of the file bytes."""

    source_label = "recorded"

    def __init__(self, recordings_dir: Path) -> None:
        self._dir = recordings_dir

    def path_for(self, content: bytes) -> Path:
        """Where the recording for these bytes lives."""
        return self._dir / f"{hashlib.sha256(content).hexdigest()}.json"

    def analyze_invoice(self, content: bytes) -> dict[str, Any]:
        path = self.path_for(content)
        if not path.exists():
            raise ExtractionError(
                "mock mode: no recorded Document Intelligence response for this file. "
                "Use INVOICEGUARD_MODE=azure or record it with `make record`."
            )
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        return data


class DocumentIntelligenceAnalyzer:
    """Calls Azure Document Intelligence with ``DefaultAzureCredential``."""

    source_label = "live"

    def __init__(self, endpoint: str, client: Any | None = None) -> None:
        if client is None:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.identity import DefaultAzureCredential

            client = DocumentIntelligenceClient(endpoint=endpoint, credential=DefaultAzureCredential())
        self._client = client

    def _analyze(self, content: bytes) -> dict[str, Any]:
        from azure.ai.documentintelligence.models import (
            AnalyzeDocumentRequest,
            DocumentAnalysisFeature,
        )
        from azure.core.exceptions import HttpResponseError, ServiceRequestError

        try:
            poller = self._client.begin_analyze_document(
                MODEL_ID,
                AnalyzeDocumentRequest(bytes_source=content),
                features=[DocumentAnalysisFeature.QUERY_FIELDS],
                query_fields=list(QUERY_FIELDS),
            )
            result = poller.result()
        except ServiceRequestError as exc:
            raise TransientError(f"Document Intelligence unreachable: {exc}") from exc
        except HttpResponseError as exc:
            status = getattr(exc, "status_code", None)
            if status == 429 or (status is not None and status >= 500):
                raise TransientError(f"Document Intelligence returned {status}") from exc
            raise ExtractionError(f"Document Intelligence rejected the file: {status}") from exc
        as_dict: dict[str, Any] = result.as_dict()
        return as_dict

    def analyze_invoice(self, content: bytes) -> dict[str, Any]:
        return call_with_retry(lambda: self._analyze(content))
