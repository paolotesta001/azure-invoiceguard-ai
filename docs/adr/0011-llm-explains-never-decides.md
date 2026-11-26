# ADR 0011 – One validated structured-output call per invoice; the LLM explains, never decides

**Status:** accepted (v1b)

## Context
Reviewers need plain-language explanations and a supplier email draft for flagged invoices.
Calling the model once per anomaly multiplies cost and latency; free-text output is hard to
attach reliably to the right anomaly.

## Decision
- One chat-completions call per flagged invoice with **structured outputs** (`InvoiceAnalysis`
  Pydantic schema): one explanation per anomaly id + an optional supplier email draft.
- Output is validated beyond the schema: every anomaly id explained exactly once, no unknown ids,
  no empty text. Invalid → **one retry** → fallback text "Explanation unavailable". Transport
  errors are retried with backoff; the pipeline never fails because of the LLM.
- The LLM output has **no influence on status or payment**: status comes from rules and policy.
- Prompt hygiene: document data is JSON inside `<invoice_data>` tags marked untrusted; IBANs are
  masked before they reach the model; temperature 0. (Prompt Shields arrive in v4.)
- Mock mode uses a deterministic template client labelled "[mock]". Recorded LLM replays are not
  used because prompts contain run-specific anomaly ids; live quality is evaluated in v3.
- In v2 the same responsibilities move into the Foundry Agent Service "InvoiceGuard Analyst"
  (tools for clause retrieval). Structured-output support with Agent Service must be re-verified
  then (one Learn page listed it as unsupported).

## Consequences
+ Cost and latency bounded per invoice; usage and estimated cost recorded per run.
+ `INVOICEGUARD_LLM_ENABLED=false` gives the rules-only baseline for the v3 experiment.
− A single bad answer affects all explanations of that invoice (mitigated by retry + fallback).
