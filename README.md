# InvoiceGuard AI

**Production-oriented, human-in-the-loop supplier-invoice validation on Microsoft Azure.**
Portfolio project applying Microsoft AI-103 (Azure AI Apps and Agents Developer Associate) skills.

> **Status: v1b – extraction + LLM explanations.** XML e-invoices (Italy, Poland), PDFs and scans,
> deterministic validation, coded auto-approval, AI explanations and a human approval inbox run
> end to end in mock mode. Retrieval/agents (v2), evaluation (v3) and Azure deployment (v4) are
> next — see [`PROGRESS.md`](PROGRESS.md). Nothing is claimed unless the code exists.

## Why
Accounts-payable teams check invoices against contracts, POs and supplier data by hand.
Typical failures: wrong prices, arithmetic errors, duplicate invoices and changed bank accounts.
**Core principle:** the system recommends; a human decides every payment above the threshold.
The LLM explains — it never decides and can never trigger a payment.

## How it works
| Step | Implementation |
|---|---|
| Ingest | Upload → SHA-256 → idempotent submission (re-upload = same result) |
| Extract | **Structured first:** FatturaPA (IT) and KSeF FA(3) (PL) XML parsed directly. **OCR fallback:** Azure Document Intelligence `prebuilt-invoice` + query fields (`PurchaseOrderNumber`, `IBAN`), confidence per field |
| Trust | Missing key fields → "needs manual entry"; low-confidence fields (< 0.80) → human review, never auto-approved |
| Store | `(supplier_id, invoice_number)` unique in PostgreSQL → duplicates rejected even under concurrency |
| Check | Plain, unit-tested Python: arithmetic, VAT rates, contract validity, currency, contract prices (structured, not RAG), IBAN checksum / mismatch / recent change |
| Explain | One **structured-output** call per flagged invoice (Azure OpenAI in Foundry, Entra ID): an explanation per anomaly + a supplier email draft. Validated, one retry, safe fallback |
| Decide | Coded policy auto-approves only clean invoices below €1,000 / PLN 4,300; payment call fails closed |
| Review | Approval inbox with backend-enforced segregation of duties, mandatory comments, editable email drafts (never sent) |
| Audit | Append-only audit log (DB trigger); IBANs masked in logs, evidence and LLM prompts |

## Quick start (no Azure subscription)
```bash
make demo        # Docker: PostgreSQL + mock ERP + UI → http://localhost:8501
# or, without Docker:
pip install -e ".[dev]" && make demo-lite
```
Invoices are uploaded by *Alice*; switch to *Bob* in the sidebar to approve them.
Mock mode replays recorded Document Intelligence responses and uses a deterministic mock LLM
(output marked "[mock]").

### Azure mode (optional)
```bash
pip install -e ".[dev,azure]" && az login
# .env: INVOICEGUARD_MODE=azure + Document Intelligence endpoint + Foundry endpoint/deployment
make record      # replace simulated DI recordings with live ones
```
Roles needed: *Cognitive Services User* (Document Intelligence, single-service resource) and
*Cognitive Services OpenAI User* (model deployment). See [`docs/sdk-notes.md`](docs/sdk-notes.md)
for what is verified and what still needs one live call.

## Demo dataset (synthetic, seed 42)
18 labelled invoices in `data/`: 12 FatturaPA, 2 KSeF, 3 PDF layouts and 1 noisy scan, covering
clean → auto-approved, wrong price, duplicate, IBAN mismatch, arithmetic error, invalid VAT rate,
currency mismatch, price increase within cap, above threshold, recently changed IBAN, unknown
SKU, expired contract and low OCR confidence. `tests/integration/test_demo_dataset.py` asserts
every label: **18/18 in mock mode**.
**Honest note:** rule checks and the *simulated* OCR recordings score perfectly by construction.
Meaningful numbers (OCR on live recordings, LLM groundedness, retrieval) come in v3.

## Development
```bash
make install  make check   # ruff + mypy --strict + pytest
make data                  # regenerate synthetic data
make tick                  # approval reminders after the timeout
```
Design decisions: [`docs/adr/`](docs/adr/) · Spec: [`SPEC.md`](SPEC.md)

## Known limitations (v1b)
No contract-clause interpretation, three-way match or split-invoice detection yet (v2) ·
no evaluation pipeline yet (v3) · no Prompt Shields / Azure deployment yet (v4) ·
KSeF exemption markers not supported · synthetic data only; no real ERP, payments or emails.
