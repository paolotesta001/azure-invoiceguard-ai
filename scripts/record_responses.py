"""Record LIVE Document Intelligence responses for every PDF/image in the invoices folder.

Overwrites the simulated recordings so mock mode replays real service output.
Requires: pip install -e ".[azure]", `az login`, and INVOICEGUARD_DOCUMENT_INTELLIGENCE_ENDPOINT.
Usage: python scripts/record_responses.py
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from invoiceguard.adapters.document_intelligence import (
    DocumentIntelligenceAnalyzer,
    RecordedAnalyzer,
)
from invoiceguard.config import AppSettings

OCR_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    if not settings.document_intelligence_endpoint:
        raise SystemExit("Set INVOICEGUARD_DOCUMENT_INTELLIGENCE_ENDPOINT first.")
    live = DocumentIntelligenceAnalyzer(settings.document_intelligence_endpoint)
    store = RecordedAnalyzer(settings.recordings_dir / "document_intelligence")
    for path in sorted(settings.invoices_dir.iterdir()):
        if path.suffix.lower() not in OCR_SUFFIXES:
            continue
        content = path.read_bytes()
        result = live.analyze_invoice(content)
        result["_recording"] = {"source": "live", "file": path.name,
                                "recorded_at": datetime.now(UTC).isoformat()}
        target = store.path_for(content)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, default=_json_default) + "\n",
                          encoding="utf-8")
        logging.info("recorded %s → %s", path.name, target.name)


if __name__ == "__main__":
    main()
