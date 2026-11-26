import threading
from pathlib import Path

import pytest

from invoiceguard.adapters.retry import TransientError
from invoiceguard.agent.explainer import FALLBACK_TEXT
from invoiceguard.agent.mock_llm import MockLlmClient
from invoiceguard.approvals.service import (
    ApprovalError,
    CommentRequiredError,
    InvalidInvoiceStateError,
    SegregationOfDutiesError,
)
from invoiceguard.config import ValidationSettings
from invoiceguard.domain.enums import DecisionType, InvoiceStatus, SubmissionStatus
from invoiceguard.domain.models import InvoiceSubmission
from invoiceguard.persistence.memory import InMemoryRepository
from tests.conftest import FakeClock, Stack, build_stack

UPLOADER, REVIEWER = "alice.uploader", "bob.reviewer"


def _submit(stack: Stack, dataset: Path, name: str, user: str = UPLOADER) -> InvoiceSubmission:
    return stack.orchestrator.submit((dataset / "invoices" / name).read_bytes(), name, user)


def test_idempotent_reupload(stack: Stack, dataset: Path) -> None:
    first = _submit(stack, dataset, "01_clean_small.xml")
    again = _submit(stack, dataset, "01_clean_small.xml")
    assert first.id == again.id
    assert len(stack.repo.list_submissions()) == 1
    assert any(e.event_type == "SUBMISSION_REPLAYED" for e in stack.repo.list_audit(first.id))


def test_clean_invoice_is_auto_approved_and_paid(stack: Stack, dataset: Path) -> None:
    sub = _submit(stack, dataset, "01_clean_small.xml")
    assert sub.status is SubmissionStatus.ACCEPTED and sub.invoice_id
    invoice = stack.repo.get_invoice(sub.invoice_id)
    assert invoice and invoice.status is InvoiceStatus.AUTO_APPROVED
    assert sub.invoice_id in stack.payments.approvals
    run = stack.repo.get_run(sub.file_sha256)
    assert run and run.status.value == "succeeded" and run.latency_ms is not None
    assert run.prompt_tokens == 0  # no anomalies → no LLM call


def test_flagged_invoice_gets_explanations_draft_and_token_usage(stack: Stack,
                                                                 dataset: Path) -> None:
    sub = _submit(stack, dataset, "02_wrong_price.xml")
    [anomaly] = stack.repo.list_anomalies(sub.id)
    assert anomaly.explanation and anomaly.explanation.startswith("[mock]")
    draft = stack.repo.get_email_draft(sub.invoice_id or "")
    assert draft and draft.generated_by == "llm:mock-llm" and "CF-26-0442" in draft.subject
    run = stack.repo.get_run(sub.file_sha256)
    assert run and run.model_deployment == "mock-llm" and run.prompt_tokens > 0
    assert any(e.event_type == "LLM_EXPLANATIONS" for e in stack.repo.list_audit(sub.id))


def test_invalid_llm_output_falls_back_without_breaking_run(tmp_path: Path, dataset: Path,
                                                            rules: ValidationSettings,
                                                            clock: FakeClock) -> None:
    stack = build_stack(InMemoryRepository(), tmp_path, dataset, rules, clock,
                        llm=MockLlmClient(bad_outputs=10))
    sub = _submit(stack, dataset, "02_wrong_price.xml")
    assert sub.status is SubmissionStatus.ACCEPTED
    [anomaly] = stack.repo.list_anomalies(sub.id)
    assert anomaly.explanation == FALLBACK_TEXT
    invoice = stack.repo.get_invoice(sub.invoice_id or "")
    assert invoice and invoice.status is InvoiceStatus.FLAGGED


def test_llm_disabled_gives_rules_only_baseline(tmp_path: Path, dataset: Path,
                                                rules: ValidationSettings,
                                                clock: FakeClock) -> None:
    stack = build_stack(InMemoryRepository(), tmp_path, dataset, rules, clock, with_llm=False)
    sub = _submit(stack, dataset, "02_wrong_price.xml")
    [anomaly] = stack.repo.list_anomalies(sub.id)
    assert anomaly.explanation is None


def test_low_confidence_scan_blocks_auto_approval(stack: Stack, dataset: Path) -> None:
    sub = _submit(stack, dataset, "16_scan_low_quality.jpg")
    invoice = stack.repo.get_invoice(sub.invoice_id or "")
    assert invoice and invoice.status is InvoiceStatus.PENDING_REVIEW
    assert invoice.needs_review_fields == ("currency", "iban", "total")
    assert stack.repo.list_anomalies(sub.id) == []
    assert sub.invoice_id not in stack.payments.approvals


def test_duplicate_is_rejected_with_critical_anomaly(stack: Stack, dataset: Path) -> None:
    original = _submit(stack, dataset, "01_clean_small.xml")
    dup = _submit(stack, dataset, "03_duplicate_of_01.xml")
    assert dup.status is SubmissionStatus.DUPLICATE_REJECTED
    assert dup.duplicate_of_invoice_id == original.invoice_id
    [anomaly] = stack.repo.list_anomalies(dup.id)
    assert anomaly.type.value == "DUPLICATE" and anomaly.severity.value == "critical"


def test_duplicate_detection_under_concurrency(tmp_path: Path, dataset: Path,
                                               rules: ValidationSettings,
                                               clock: FakeClock) -> None:
    stack = build_stack(InMemoryRepository(), tmp_path, dataset, rules, clock)
    base = (dataset / "invoices" / "01_clean_small.xml").read_bytes()
    variants = [base.replace(b"00001</ProgressivoInvio>", f"{i:05d}</ProgressivoInvio>".encode())
                for i in range(10, 18)]
    barrier = threading.Barrier(len(variants))
    results: list[InvoiceSubmission] = []

    def worker(content: bytes) -> None:
        barrier.wait()
        results.append(stack.orchestrator.submit(content, "x.xml", UPLOADER))

    threads = [threading.Thread(target=worker, args=(v,)) for v in variants]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted(r.status.value for r in results)
    assert statuses.count("accepted") == 1
    assert statuses.count("duplicate_rejected") == len(variants) - 1


def test_unknown_supplier_and_unrecorded_pdf_fail_visibly(stack: Stack, dataset: Path) -> None:
    xml = (dataset / "invoices" / "01_clean_small.xml").read_bytes().replace(
        b"01000000011", b"07777777777")
    sub = stack.orchestrator.submit(xml, "unknown.xml", UPLOADER)
    assert sub.status is SubmissionStatus.FAILED and "Unknown supplier" in (sub.failure_reason or "")
    pdf = stack.orchestrator.submit(b"%PDF-1.7 not recorded", "scan.pdf", UPLOADER)
    assert pdf.status is SubmissionStatus.FAILED and "no recorded" in (pdf.failure_reason or "")


def test_payment_gateway_failure_fails_closed(tmp_path: Path, dataset: Path,
                                              rules: ValidationSettings, clock: FakeClock,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    stack = build_stack(InMemoryRepository(), tmp_path, dataset, rules, clock)
    monkeypatch.setattr("invoiceguard.adapters.retry.time.sleep", lambda _s: None)

    def boom(invoice_id: str, approved_by: str) -> str:
        raise TransientError("ERP down")

    monkeypatch.setattr(stack.payments, "approve_payment", boom)
    sub = _submit(stack, dataset, "01_clean_small.xml")
    invoice = stack.repo.get_invoice(sub.invoice_id or "")
    assert invoice and invoice.status is InvoiceStatus.PENDING_REVIEW


def test_segregation_of_duties_enforced_in_backend(stack: Stack, dataset: Path) -> None:
    sub = _submit(stack, dataset, "02_wrong_price.xml")
    assert sub.invoice_id
    with pytest.raises(SegregationOfDutiesError):
        stack.orchestrator.record_decision(sub.invoice_id, UPLOADER, DecisionType.APPROVE)
    assert any(e.event_type == "DECISION_BLOCKED_SOD" for e in stack.repo.list_audit(sub.id))
    decision = stack.orchestrator.record_decision(sub.invoice_id, REVIEWER, DecisionType.APPROVE)
    assert decision.payment_reference
    invoice = stack.repo.get_invoice(sub.invoice_id)
    assert invoice and invoice.status is InvoiceStatus.APPROVED
    with pytest.raises(InvalidInvoiceStateError):
        stack.orchestrator.record_decision(sub.invoice_id, "carol.reviewer",
                                           DecisionType.REJECT, "x")


def test_reject_requires_comment_and_does_not_pay(stack: Stack, dataset: Path) -> None:
    sub = _submit(stack, dataset, "04_iban_mismatch.xml")
    assert sub.invoice_id
    with pytest.raises(CommentRequiredError):
        stack.orchestrator.record_decision(sub.invoice_id, REVIEWER, DecisionType.REJECT, "  ")
    stack.orchestrator.record_decision(sub.invoice_id, REVIEWER, DecisionType.REJECT,
                                       "IBAN not confirmed by supplier")
    assert sub.invoice_id not in stack.payments.approvals


def test_reviewer_can_edit_email_draft(stack: Stack, dataset: Path) -> None:
    sub = _submit(stack, dataset, "02_wrong_price.xml")
    draft = stack.orchestrator.update_email_draft(sub.invoice_id or "", REVIEWER,
                                                  "Price question", "Please explain the price.")
    assert draft.updated_by == REVIEWER and draft.generated_by.startswith("llm:")
    assert stack.repo.get_email_draft(sub.invoice_id or "") == draft
    with pytest.raises(ApprovalError):
        stack.orchestrator.update_email_draft(sub.invoice_id or "", REVIEWER, " ", "body")
    assert any(e.event_type == "EMAIL_DRAFT_EDITED" for e in stack.repo.list_audit(sub.id))


def test_reminder_after_timeout_once(stack: Stack, dataset: Path, clock: FakeClock) -> None:
    sub = _submit(stack, dataset, "09_clean_above_threshold.xml")
    assert stack.orchestrator.check_timeouts() == []
    clock.advance(hours=72)
    assert stack.orchestrator.check_timeouts() == [sub.invoice_id]
    assert stack.orchestrator.check_timeouts() == []


def test_audit_and_llm_prompt_never_contain_full_iban(stack: Stack, dataset: Path) -> None:
    sub = _submit(stack, dataset, "04_iban_mismatch.xml")
    invoice = stack.repo.get_invoice(sub.invoice_id or "")
    assert invoice and invoice.data.iban
    dump = str([e.payload for e in stack.repo.list_audit()]) + str(
        [a.evidence for a in stack.repo.list_anomalies(sub.id)])
    assert invoice.data.iban not in dump
