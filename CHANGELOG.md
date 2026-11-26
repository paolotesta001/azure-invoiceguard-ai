# Changelog

## [0.2.0] – v1b Extraction + LLM explanations
### Added
- KSeF FA(3) XML parser (Polish e-invoices; NRB → IBAN normalisation; PLN conversion fields ignored).
- Document Intelligence `prebuilt-invoice` adapter with query fields (`PurchaseOrderNumber`, `IBAN`),
  pure REST-JSON mapper with per-field confidence, and a recorded-response adapter for mock mode.
- Confidence handling: missing key fields → "needs manual entry"; other missing/low-confidence
  fields → `needs_review_fields` (blocks auto-approval) with UI highlighting.
- LLM layer: `LlmClient` interface, Azure OpenAI client (structured outputs, Entra ID),
  deterministic mock client, `ExplanationService` with id validation, one retry and fallback.
- Anomaly explanations labelled "AI-generated", editable supplier email drafts (never sent),
  token usage + configurable cost estimate per run.
- Synthetic data: 3 PDF layouts, a noisy scan, 2 KSeF invoices, simulated DI recordings
  (18 labelled invoices in total); `make record` for live recordings.
- Migration 0002 (`supplier_email_drafts`), ADR 0011.

## [0.1.0] – v1a Core without LLM
- Domain model, PostgreSQL schema with append-only audit, submission model with idempotent
  re-upload and concurrency-safe duplicate rejection, FatturaPA parser, deterministic checks,
  coded auto-approval, approval service with segregation of duties, mock ERP, Streamlit UI,
  synthetic data generator, Docker Compose demo, CI.
