# ADR 0010 – Store every upload as a submission; duplicates are rejected submissions

**Status:** accepted (v1a)

## Context
`(supplier_id, invoice_number)` is a database unique constraint so duplicates are impossible even
under concurrency. But if the insert simply fails, there is no record to attach the critical
DUPLICATE anomaly to, and the reviewer never sees that a duplicate was attempted.

## Decision
- `invoice_submissions` stores every uploaded file (unique on `file_sha256` → idempotent re-upload).
- `invoices` stores accepted invoices only (unique on supplier + number).
- On a unique-constraint violation the submission becomes `duplicate_rejected`, points to the
  original via `duplicate_of_invoice_id`, and gets a CRITICAL `DUPLICATE` anomaly.

## Consequences
+ Concurrency-safe by construction (tested with parallel inserts).
+ Duplicates, failures and replays are visible in the UI and audit trail.
− One more table and status field to maintain.
