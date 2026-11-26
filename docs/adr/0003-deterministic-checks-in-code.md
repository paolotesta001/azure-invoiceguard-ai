# ADR 0003 – Deterministic checks run in code, not in the LLM

**Status:** accepted (v1a)

## Context
Invoice validation is mostly arithmetic and lookups: totals, VAT, contract prices, IBAN, duplicates.
LLMs are probabilistic, can miscalculate, and are exposed to prompt injection from document text.

## Decision
Every calculation, comparison, threshold and approval rule is a plain Python function in
`src/invoiceguard/checks/` and `src/invoiceguard/policy/`, with unit tests. Money is `Decimal`
with `ROUND_HALF_UP` applied only in `domain/money.py`. The LLM only explains findings,
interprets ambiguous clauses (v2) and drafts supplier emails.

## Consequences
+ Same input → same result; every finding is reproducible and auditable.
+ A malicious invoice cannot "talk" the system into approving a payment.
+ No tokens are spent on arithmetic.
− New rules require code changes (acceptable: rules change rarely and need review anyway).
− On synthetic data built for these rules, rule metrics will be near 100%; the README says so.
