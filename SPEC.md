# InvoiceGuard AI — Project Specification

> Single source of truth for the project. The coding agent must read this file, `AGENTS.md` and `PROGRESS.md` at the start of every session.
> Spec version: 1.2 (changes are listed in `PROGRESS.md → Decisions`)

---

## 1. Problem and goal

Accounts-payable (AP) teams manually check supplier invoices against contracts, purchase orders (POs) and deliveries. Errors and fraud are common: wrong prices, wrong totals, duplicate invoices, items invoiced but never delivered, changed bank accounts, and invoices split to stay under approval limits.

InvoiceGuard AI automates invoice validation:

1. Ingests an invoice (structured XML e-invoice or PDF/scan).
2. Extracts the data.
3. Runs deterministic checks against structured contract terms, POs, goods receipts and supplier master data.
4. Uses an LLM to interpret ambiguous contract clauses, explain anomalies with citations and draft supplier emails.
5. Auto-approves only clean, low-value invoices through a coded policy. Everything else goes to a human reviewer.
6. Keeps a complete audit trail.

**Core principle:** the system recommends; a human decides every payment above the threshold. No payment can ever be triggered by the LLM alone.

Purpose of the repository: a portfolio project demonstrating Microsoft AI-103 (Azure AI Apps and Agents Developer Associate) skills applied in a realistic, production-oriented way.

---

## 2. Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.11+ |
| Data models | Pydantic v2; money as `decimal.Decimal`, never `float` |
| Relational store | Azure Database for PostgreSQL – Flexible Server (local: PostgreSQL in Docker), SQLAlchemy 2 + Alembic |
| File storage | Azure Blob Storage (local: content-addressed local folder in v1–v2; Azurite from v3 with the Blob trigger) |
| Document extraction | Azure Document Intelligence `prebuilt-invoice` with query fields (`azure-ai-documentintelligence` 1.0.x, API 2024-11-30) |
| E-invoice parsing | `lxml` for Italian FatturaPA XML and Polish KSeF FA(3) XML |
| LLM / agents | Microsoft Foundry model deployment (GPT-4.1-class or newer, Global Standard in dev); v1b: structured-output chat completions; v2: Foundry Agent Service |
| Retrieval | Azure AI Search: hybrid (keyword + vector), semantic ranker, filters, integrated vectorizer |
| Orchestration | `Orchestrator` interface: `LocalOrchestrator` (mock mode, v1–v2) and Azure Durable Functions (Python) from v3 |
| Mock ERP | FastAPI service with OpenAPI 3.0 spec |
| UI | Streamlit |
| Evaluation | Azure AI Evaluation SDK / Foundry evaluations |
| Observability | OpenTelemetry → Azure Monitor Application Insights |
| Infrastructure | Bicep + Azure Developer CLI (`azd up`) |
| CI/CD | GitHub Actions |
| Local dev | Docker Compose, `Makefile` |

### 2.1 SDK rules
- Pin every dependency version in `pyproject.toml`. Azure SDKs live in the optional `azure` extra; mock mode never imports them.
- Record every SDK assumption (package, version, method, Learn page consulted, date, verified / to verify) in `docs/sdk-notes.md`.
- Foundry Agent Service has more than one API generation. Target the current one documented on Microsoft Learn at implementation time, write which one in `docs/sdk-notes.md`, and keep every agent call inside `src/invoiceguard/adapters/foundry_agent.py`.
- If unsure about a method or parameter, say so explicitly and keep the call isolated in its adapter.

---

## 3. Domain model (Pydantic + SQL tables)

**Supplier:** `id`, `name`, `vat_id`, `country` (IT/PL/other), `currency`, `iban_on_file`, `iban_last_changed_at`, `status` (active/blocked).

**Contract:** `id`, `supplier_id`, `version`, `valid_from`, `valid_to`, `supersedes_contract_id`, `payment_terms_days`, `early_payment_discount_pct`, `late_penalty_pct`, `max_price_increase_pct`, `currency`, `source_document_uri`.

**ContractClause** (v2): `id`, `contract_id`, `clause_ref` (e.g. "§4.2"), `title`, `text`.

**ContractPriceItem:** `contract_id`, `sku`, `description`, `unit_price`, `currency`, `unit`.

**PurchaseOrder + PurchaseOrderLine**, **GoodsReceipt + GoodsReceiptLine** (as in v1a).

**InvoiceSubmission** (every uploaded file): `id`, `file_sha256` (unique), `filename`, `file_uri`, `uploaded_by`, `uploaded_at`, `status` (received / processing / accepted / duplicate_rejected / failed), `invoice_id`, `duplicate_of_invoice_id`, `failure_reason`, `retry_count`.

**Invoice + InvoiceLine** (accepted invoices only): header fields, `source_type` (`xml_fatturapa`, `xml_ksef`, `ocr`), `field_confidence` (header fields + aggregated `lines.<field>` = lowest confidence across lines), `needs_review_fields`, `status` (processing / auto_approved / flagged / pending_review / approved / rejected / clarification_requested), `status_changed_at`, `reminder_sent_at`. **Unique: (`supplier_id`, `invoice_number`).**

**Duplicate flow:** on unique-constraint violation the submission becomes `duplicate_rejected` with `duplicate_of_invoice_id` and a `critical` DUPLICATE anomaly (ADR 0010). Concurrency-safe.

**Anomaly:** `id`, `submission_id`, `invoice_id` (nullable), `type`, `severity`, `message` (deterministic rule text), `monetary_impact`, `evidence` (JSON, masked), `explanation` (LLM, nullable), `detected_by`.

**SupplierEmailDraft** (v1b): `id`, `invoice_id` (unique), `subject`, `body`, `generated_by` (`llm:<model>` or `user:<id>`), `updated_by`, `updated_at`. Draft only; never sent.

**ValidationRun:** `run_id` (= `file_sha256`), `submission_id`, `status`, `mode`, timestamps, `latency_ms`, `model_deployment`, `prompt_tokens`, `completion_tokens`, `estimated_cost`.

**ApprovalDecision:** `invoice_id`, `decision`, `reviewer_id`, `comment`, `signed_token_id` (v4), `payment_reference`, `decided_at`.

**AuditEvent:** append-only (PostgreSQL trigger), payload masked.

### 3.1 Money rules
- `Decimal` everywhere; `ROUND_HALF_UP` to 2 decimals only in `domain/money.py`. Floats from SDK JSON are converted via `str` (shortest representation).
- EUR and PLN; VAT rates per country in config (IT 22/10/5/4%, PL 23/8/5/0%). No currency conversion.

---

## 4. Processing pipeline

### 4.1 Ingestion
Upload via Streamlit (v3: Blob container). Idempotency by `sha256(file_bytes)`. `Orchestrator` interface: `LocalOrchestrator` (v1–v2, state in DB, timeouts via `make tick`), Durable Functions (v3). Unexpected errors → submission `failed` ("Failed – needs attention"); v3 adds retries + poison queue.

### 4.2 Extraction
- **XML (preferred):** format detected from the root element; FatturaPA and KSeF FA(3) parsed with hardened `lxml`; confidence 1.0. Unsupported KSeF VAT markers (e.g. `zw`) fail explicitly.
- **PDF/image:** Document Intelligence `prebuilt-invoice` with query fields `PurchaseOrderNumber` and `IBAN`; the field with the higher confidence wins. Mapping is a pure function on the REST-shaped JSON (`ingestion/di_mapping.py`).
  - Missing **key** fields (supplier VAT id, invoice number, date, total with currency, line items) → submission fails with "needs manual entry".
  - Any other missing, derived or low-confidence field (default threshold 0.80) → confidence 0 / low → `needs_review_fields` → auto-approval blocked, highlighted in the UI.
- **Mock mode:** `RecordedAnalyzer` replays `data/recorded/document_intelligence/<sha256>.json`. Recordings are *simulated* (generated from ground truth, labelled) until replaced by *live* ones with `make record`. Unrecorded PDFs fail with a clear message.
- Unknown supplier VAT id → submission `failed` with an actionable reason.

### 4.3 Deterministic checks (plain Python, 100% unit tested)

| Anomaly type | Check | Severity | Version |
|---|---|---|---|
| ARITHMETIC | Line totals, subtotal, VAT and total consistency (tolerance 0.01) | high | v1a |
| VAT_RATE | VAT rate not valid for supplier country | medium | v1a |
| NO_VALID_CONTRACT | No contract version valid on `invoice_date` | high | v1a |
| CURRENCY | Invoice currency ≠ contract currency (price check skipped) | medium | v1a |
| PRICE_ABOVE_CAP / PRICE_INCREASE_WITHIN_CAP | Unit price vs. `ContractPriceItem` | high / low | v1a |
| SKU_NOT_IN_CONTRACT | Line SKU missing or not priced | high | v1a |
| DUPLICATE | DB unique constraint | critical | v1a |
| IBAN_MISSING / IBAN_INVALID / IBAN_MISMATCH / IBAN_RECENTLY_CHANGED | Bank-account checks | medium / critical | v1a |
| CONTRACT_VERSION | Amendment boundary handling | high | v2 |
| THREE_WAY | Invoice qty vs. PO qty vs. goods-receipt qty | high | v2 |
| PO_STATUS | PO missing, closed or another supplier's | high | v2 |
| NEAR_DUPLICATE | Same supplier + total + date within 7 days, different number | critical | v2 |
| SPLIT | ≥2 invoices, same supplier, within 14 days, each ≥ 0.80 × threshold and < threshold, together > threshold | high | v2 |
| PAYMENT_TERMS | Due date inconsistent with contract terms | low | v2 |

### 4.4 LLM layer
- **v1b (implemented):** one structured-output call per flagged invoice (`InvoiceAnalysis`: one explanation per anomaly id + optional supplier email draft). Validation beyond the schema (all ids exactly once, no unknown ids, no empty text) → one retry → fallback "Explanation unavailable". LLM output never changes status or payment (ADR 0011). Document data passed as JSON in `<invoice_data>` tags marked untrusted; IBANs masked; temperature 0. Token usage + cost estimate (prices from `config/settings.yaml`) stored per run. `INVOICEGUARD_LLM_ENABLED=false` = rules-only baseline.
- **Mock mode:** deterministic template client, output prefixed "[mock]".
- **v2:** one Foundry Agent Service agent, **"InvoiceGuard Analyst"** (ADR 0001), with the OpenAPI tool (mock ERP, read-only) and the Azure AI Search tool (clause wording only; prices never from search, ADR 0002); clause interpretation with `clause_ref` citations; no tool can approve a payment; reachability per ADR 0006. Re-verify structured-output support with Agent Service before implementing.

### 4.5 Decision policy (code) — auto-approve only if no anomalies, no `needs_review` fields, total < threshold for the currency (EUR 1,000; PLN 4,300; missing threshold → no auto-approval), supplier active. Auto-approval fails closed if the ERP call fails.

### 4.6 Human approval — timeout 72 h → one reminder; segregation of duties in the backend; comment mandatory for reject and clarification; supplier email draft editable (audited, never sent); `approve_payment` backend-only (v1–v3), signed token (v4).

### 4.7 "Ask InvoiceGuard" (v2) — query catalog (read-only role) for data questions; RAG with citations for documents; explicit "I don't have enough information" fallback.

---

## 5. Streamlit UI
MOCK MODE banner (mentions recorded DI + mock LLM); user selector; LLM label in the sidebar. **Dashboard** (status, source, anomalies, needs-review fields, impact; filters by status/supplier/source). **Upload** (XML, PDF, images). **Detail** (fields with confidence and ⚠️ below threshold, lines, anomalies with "🤖 AI-generated" explanations, run tokens/cost, masked audit trail). **Approval inbox** (needs-review warning, anomalies, editable email draft, decision form). Ask InvoiceGuard (v2), Runs & costs (v3).

---

## 6. Security and Responsible AI
Managed identity + least-privilege RBAC (`docs/security.md`, v4); Key Vault; Prompt Shields on extracted text (v4) with injection test; content filters documented; IBAN masking in logs, audit, evidence **and LLM prompts**; hardened XML; private endpoints in prod (v4).

---

## 7. Evaluation and quality
Golden dataset via `scripts/generate_synthetic_data.py` (seed 42). v1b: 18 labelled invoices (12 FatturaPA, 2 KSeF, 3 PDF layouts, 1 noisy scan). v3: ≥60 invoices, 10 suppliers, 12 contracts incl. 3 amendments, prompt-injection invoice. Metrics, experiments (rules-only vs. rules + LLM; retrieval ablation), CI quality gate, feedback loop as before. **Honesty note:** rule checks and simulated OCR recordings score near 100% by construction; meaningful OCR metrics require live recordings.

---

## 8. Observability and reliability
OpenTelemetry → App Insights (v3); backoff + jitter + `retry-after` (implemented for ERP, Document Intelligence and LLM calls); alerts in Bicep (v4).

---

## 9. Mock mode (required)
`make demo` (Docker: PostgreSQL, mock ERP, Streamlit; migrations; seed; 18 demo invoices processed) or `make demo-lite` (in-memory). No Azure credentials, no Functions runtime, no Azure SDKs. Recorded DI responses + deterministic mock LLM. README states which numbers are live vs. mock.

---

## 10. Infrastructure and deployment (v4)
Bicep modules, `azd up`/`azd down`, dev/prod profiles, deployment-type ADR, budget alert, cost warning.

---

## 11. Repository structure
```
invoiceguard-ai/
├── README.md  SPEC.md  AGENTS.md  PROGRESS.md  PROMPTS.md  CHANGELOG.md
├── Makefile  Dockerfile  docker-compose.yml  alembic.ini  .env.example  pyproject.toml
├── config/settings.yaml
├── data/  seed/  invoices/  labels/  recorded/document_intelligence/
├── migrations/
├── src/invoiceguard/
│   ├── domain/  config.py  bootstrap.py  seed.py
│   ├── db/  persistence/  ingestion/  checks/  policy/  approvals/  orchestration/  safety/
│   ├── adapters/   # retry, file store, payments, document_intelligence, llm
│   ├── agent/      # schemas, instructions, explainer, mock_llm
│   └── retrieval/  telemetry/        # v2–v3
├── mock_erp/  ui/  scripts/  tests/  docs/ (sdk-notes.md, adr/)  .github/workflows/
```

---

## 12. Versions and acceptance criteria
**v1a – Core without LLM** ✔ approved.
**v1b – Extraction + LLM explanations.** *Acceptance:* a PDF invoice is extracted in mock mode with confidences; a low-confidence field blocks auto-approval; every flagged anomaly shows a labelled AI explanation; invalid LLM output falls back without breaking the run.
**v2 – Grounded + AP depth.** *Acceptance:* ambiguous clauses classified with a valid `clause_ref`; aggregation answers correct from SQL; explicit fallback.
**v3 – Quality + reliability.** *Acceptance:* CI fails on a degraded prompt; re-upload creates no new run; failing file ends in "Failed – needs attention".
**v4 – Hardened + deployed.** *Acceptance:* `approve_payment` without token → 401/403; injection invoice flagged and not obeyed; `azd up` from a clean subscription; `azd down` removes everything.
**v5 – Polish.**

---

## 13. AI-103 skill mapping (README — add a row only when the code exists)
| AI-103 skill area | Where in the repo |
|---|---|
| Plan & manage: deployment types, managed identity, RBAC, private endpoints, monitoring, cost | `infra/`, `docs/security.md`, `docs/adr/` |
| Responsible AI: content filters, Prompt Shields, human-in-the-loop | `src/invoiceguard/safety/`, `src/invoiceguard/approvals/`, `tests/injection/` |
| Generative AI & agents: structured outputs (v1b), Foundry Agent Service + OpenAPI tool (v2) | `src/invoiceguard/agent/`, `src/invoiceguard/adapters/llm.py` |
| RAG: hybrid search, semantic ranker, filters, integrated vectorizer | `src/invoiceguard/retrieval/` |
| Evaluation: Groundedness, Task Adherence, Tool Call Accuracy, red teaming, CI gate | `evaluation/`, `.github/workflows/eval.yml` |
| Information extraction: Document Intelligence `prebuilt-invoice` + query fields | `src/invoiceguard/adapters/document_intelligence.py`, `src/invoiceguard/ingestion/` |
| Observability: tracing with Application Insights | `src/invoiceguard/telemetry/`, `docs/observability.md` |

---

## 14. ADRs (`docs/adr/`)
0001 single agent · 0002 structured prices, not RAG · 0003 deterministic checks in code ✔ · 0004 fixed workflow · 0005 hybrid search + semantic ranker · 0006 ERP reachability · 0007 orchestrator interface ✔ · 0008 deployment types · 0009 query catalog · 0010 submission model ✔ · 0011 LLM explains, never decides ✔.

---

## 15. Out of scope (README "Known limitations")
Real ERP integration, payments, email sending; currency conversion; KSeF/SDI API submission (parsing only); production auth beyond Entra ID Easy Auth; computer vision beyond document OCR.
