# PROGRESS.md — InvoiceGuard AI

> Updated by the coding agent at the end of every task. Status: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

## Current status
- **Current version:** v1b – code complete, awaiting owner verification (V1B-10) and approval
- **Last completed task:** V1B-09
- **Next task:** V1B-10 (local `make format && make check`, `make demo`; optional one live Azure call), then plan v2
- **Blockers:** none

---

## v1a – Core without LLM ✔ approved
- [x] V1A-01 … V1A-16 (scaffold, domain, DB + migrations, generator, FatturaPA parser, checks, duplicate flow, IBAN, policy, orchestrator, approvals, mock ERP, UI, Docker, acceptance, ADRs)
- [ ] V1A-17 Owner verification → merged into V1B-10 (same commands)

## v1b – Extraction + LLM explanations
- [x] V1B-01 KSeF FA(3) parser (`ingestion/ksef.py`) + tests (NRB → IBAN, P_14_xW ignored, VAT markers)
- [x] V1B-02 Document Intelligence adapter (real, lazy SDK import, retry/transient mapping) + query fields (`PurchaseOrderNumber`, `IBAN`)
- [x] V1B-03 Recorded DI adapter + REST-JSON mapper (`ingestion/di_mapping.py`) + simulated recordings in `data/recorded/` + `make record`
- [x] V1B-04 Synthetic PDFs (ReportLab, 3 layouts, reproducible) + noisy JPEG scan (Pillow)
- [x] V1B-05 Confidence handling: key fields → "needs manual entry"; others → `needs_review_fields` → blocks auto-approval; UI highlighting
- [x] V1B-06 LLM adapter (Azure OpenAI structured outputs, Entra ID) + deterministic mock + validation, one retry, fallback
- [x] V1B-07 Anomaly explanations labelled "AI-generated" + editable supplier email drafts (migration 0002) + token/cost per run
- [x] V1B-08 `docs/sdk-notes.md` (verified vs. to-verify), ADR 0011
- [x] V1B-09 Acceptance tests (18 labelled invoices) + UI smoke tests
- [ ] V1B-10 Owner verification
  - [ ] `pip install -e ".[dev]"` with pinned versions
  - [ ] `make format` → `make lint` clean
  - [ ] `make typecheck` (mypy --strict) clean — fix findings if any
  - [ ] `make test` green locally (SQLite SQL tests + UI tests)
  - [ ] CI green on GitHub (PostgreSQL: migrations 0001+0002 vs. models, concurrency, append-only)
  - [ ] `make demo` → 18 submissions; approve one as Bob; edit an email draft
  - [ ] Optional live check: `pip install -e ".[azure]"`, `az login`, set endpoints, `make record`, then one run with `INVOICEGUARD_MODE=azure`
  - [ ] Validate one FatturaPA and one KSeF sample against the official XSDs (OI-2, OI-3)

### v1b acceptance (SPEC §12)
| Criterion | Evidence | Result |
|---|---|---|
| PDF extracted in mock mode with confidences | `test_di_mapping.py::test_maps_clean_pdf_with_confidences`, `test_ingestion.py::test_extractor_routes_formats` | ✅ |
| Low-confidence field blocks auto-approval | `test_pipeline_and_approvals.py::test_low_confidence_scan_blocks_auto_approval`, `test_policy.py::test_low_confidence_field_blocks` | ✅ |
| Every flagged anomaly shows a labelled AI explanation | `test_demo_dataset.py::test_all_demo_invoices_match_labels`, `test_ui.py::test_inbox_blocks_uploader_and_allows_reviewer` | ✅ |
| Invalid LLM output falls back without breaking the run | `test_llm.py::test_invalid_output_twice_falls_back`, `test_pipeline_and_approvals.py::test_invalid_llm_output_falls_back_without_breaking_run` | ✅ |

### Verification status
| What | Where | Result |
|---|---|---|
| 77 unit + integration tests (incl. 18-invoice acceptance, LLM retry/fallback, DI mapping, KSeF, concurrency) | build sandbox | ✅ pass |
| Streamlit pages incl. scan detail, inbox AI labels, save draft | build sandbox (`AppTest`, tables stubbed: sandbox pyarrow/NumPy mismatch) | ✅ no exceptions |
| SQL repository, migrations 0001–0002, PostgreSQL trigger | not available in sandbox | ⏳ CI / local |
| ruff, mypy, Docker | not available in sandbox | ⏳ local |
| Live Document Intelligence / Azure OpenAI calls | no Azure access from sandbox | ⏳ optional, owner |

## v2 – Grounded + AP depth
- [ ] V2-01 ContractClause model + contract amendments; CONTRACT_VERSION check
- [ ] V2-02 THREE_WAY + PO_STATUS checks (goods receipts)
- [ ] V2-03 NEAR_DUPLICATE + SPLIT + PAYMENT_TERMS checks
- [ ] V2-04 AI Search index (hybrid, semantic config, integrated vectorizer) + indexing script
- [ ] V2-05 Retrieval module (filters supplier_id + contract_version) + mock adapter
- [ ] V2-06 InvoiceGuard Analyst agent (Foundry Agent Service) + OpenAPI tool + Search tool
- [ ] V2-07 Clause interpretation with citations + tests
- [ ] V2-08 Query catalog (read-only DB role) + Ask InvoiceGuard router + RAG + fallback
- [ ] V2-09 UI: Ask InvoiceGuard page; evidence view with clause citations
- [ ] V2-10 ADRs 0001, 0002, 0004, 0005, 0006, 0009 + acceptance check

## v3 – Quality + reliability
- [ ] V3-01 Full golden dataset (≥60 invoices, 10 suppliers, 12 contracts incl. 3 amendments) + labels
- [ ] V3-02 Metrics: extraction accuracy, P/R/F1 per anomaly type, FP rate, latency, cost
- [ ] V3-03 Foundry evaluators: Groundedness, Relevance, Task Adherence, Tool Call Accuracy
- [ ] V3-04 Experiments: rules-only vs rules+LLM; retrieval ablation (recall@5, MRR)
- [ ] V3-05 `thresholds.yaml` + `eval.yml` CI gate; degraded-prompt test PR
- [ ] V3-06 DurableOrchestrator: Blob trigger (Azurite locally), idempotency, approval wait + timeout/reminder
- [ ] V3-07 Retries + poison queue; "Failed – needs attention" with retry action
- [ ] V3-08 OpenTelemetry → Application Insights; Runs & costs page
- [ ] V3-09 Feedback loop → `evaluation/candidates/`
- [ ] V3-10 Acceptance check

## v4 – Hardened + deployed
- [ ] V4-01 Signed approval tokens (Key Vault key) on `approve_payment` + 401/403 tests
- [ ] V4-02 Prompt Shields adapter + injection invoice + test
- [ ] V4-03 Masking review (logs, traces, eval outputs)
- [ ] V4-04 Bicep modules + `azure.yaml`; dev profile; `azd up` / `azd down`
- [ ] V4-05 Managed identities + role assignments; `docs/security.md`
- [ ] V4-06 Prod profile: private endpoints, public access disabled
- [ ] V4-07 Content filter config + custom blocklist (documented)
- [ ] V4-08 Alerts (error rate, p95 latency, cost) + budget + `teardown.sh`
- [ ] V4-09 AI Red Teaming scan (ASR) + ADR 0008
- [ ] V4-10 Acceptance check

## v5 – Polish
- [ ] V5-01 Architecture diagram + `docs/architecture.md`
- [ ] V5-02 README: problem, demo GIF, results tables (live vs. mock), quick start
- [ ] V5-03 AI-103 skill table (only rows with existing code) + ADR index
- [ ] V5-04 Known limitations + next steps
- [ ] V5-05 CI badges, `CONTRIBUTING.md`, Issues/PRs history
- [ ] V5-06 Final review against SPEC.md

---

## Decisions log
| Date | Task | Decision | Reason |
|---|---|---|---|
| 2026-11-13 | V1A-07 | Price increases within the cap → LOW anomaly `PRICE_INCREASE_WITHIN_CAP` | A human confirms adjustments until v2 clause interpretation exists |
| 2026-11-13 | V1A-07 | Added `SKU_NOT_IN_CONTRACT` (high) | An unpriced item cannot be validated |
| 2026-11-13 | V1A-06 | Contract selection + `NO_VALID_CONTRACT` in v1a | Needed by the price check; amendments stay in v2 |
| 2026-11-13 | V1A-09 | IBAN checks split into MISSING / INVALID / MISMATCH / RECENTLY_CHANGED | Clearer evidence |
| 2026-11-13 | V1A-12 | Comment required for reject and request clarification | A clarification needs a question |
| 2026-11-13 | V1A-15 | Local folder file store in v1–v2; Azurite in v3 | Keeps `make demo` fast |
| 2026-11-13 | V1A-13 | ERP port not published; payment endpoint excluded from OpenAPI | Defence in depth before signed tokens |
| 2026-11-13 | V1A-01 | `E501` ignored in lint; `ruff format` enforces length | One source of truth |
| 2026-11-18 | V1B-06 | One structured call per flagged invoice; validation + one retry + fallback; LLM never changes status (ADR 0011) | Bounded cost; reliable mapping to anomaly ids |
| 2026-11-18 | V1B-06 | Mock LLM = deterministic template ("[mock]"), no recorded LLM replays | Prompts contain run-specific ids; live quality measured in v3 |
| 2026-11-18 | V1B-03 | DI recordings stored in `data/recorded/` (generated with the dataset), simulated until `make record` | Demo and tests need them at runtime; honesty label in each file |
| 2026-11-18 | V1B-05 | Missing key fields → "needs manual entry" failure; other missing/derived fields → confidence 0 | Duplicate detection needs key fields; nothing silently trusted |
| 2026-11-18 | V1B-06 | v1b uses Azure OpenAI structured outputs directly; Agent Service in v2 | Matches SPEC §4.4; structured outputs + agents must be re-verified |
| 2026-11-18 | V1B-07 | LLM cost from configured token prices (default 0) | Prices vary by model/region/deployment type; never hard-coded |
| 2026-11-18 | V1B-01 | Unsupported KSeF VAT markers (`zw`, `np`, …) fail explicitly | No silent 0% mapping |
| 2026-11-18 | V1B-04 | PO quantities in seed data raised to 300 | Room for v2 three-way-match scenarios |
| 2026-11-18 | — | Plan for v1b presented; owner asked to proceed ("keep working") | Proceeded with the 5 proposed decisions |

## Open issues
| ID | Description | Found in | Status |
|---|---|---|---|
| OI-1 | ruff/mypy/SQL/Docker not runnable in the build sandbox — verify locally | V1A/V1B | open |
| OI-2 | FatturaPA samples not validated against the official XSD | V1A-05 | open |
| OI-3 | KSeF FA(3) element codes + namespace to verify against official XSD/sample | V1B-01 | open |
| OI-4 | DI query-field call shape, `as_dict()` and prebuilt-invoice field names to verify with one live call | V1B-02 | open |
| OI-5 | Pinned `openai` / `azure-identity` versions to verify (callable `api_key` support) | V1B-06 | open |

## Manual Azure configuration (optional for v1b; mock mode needs none)
| Resource / setting | Notes |
|---|---|
| Document Intelligence **single-service** resource | Required for Entra ID auth; role **Cognitive Services User** for your identity |
| Foundry / Azure OpenAI resource + GPT-4.1-class deployment (Global Standard) | Role **Cognitive Services OpenAI User**; set `INVOICEGUARD_OPENAI_ENDPOINT`, `INVOICEGUARD_LLM_DEPLOYMENT` |
| Token prices in `config/settings.yaml → llm_pricing` | From the Azure pricing page for your model/region |

## Measured results (mark live vs. mock)
| Metric | Value | Mode | Date |
|---|---|---|---|
| Labelled demo invoices matching expected status, anomalies and review fields | 18 / 18 | mock (in-memory, simulated DI, mock LLM) | 2026-11-18 |
