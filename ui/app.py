"""InvoiceGuard AI – Streamlit UI (dashboard, upload, evidence view, approval inbox).

Run: ``streamlit run ui/app.py``. In mock mode a banner is always shown.
The sidebar user selector simulates roles; in Azure mode Entra ID (Easy Auth) replaces it (v4).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd
import streamlit as st

from invoiceguard.agent.explainer import FALLBACK_TEXT
from invoiceguard.approvals.service import ApprovalError
from invoiceguard.bootstrap import AppContext, build_context
from invoiceguard.domain.enums import DecisionType, InvoiceStatus, Mode, Severity
from invoiceguard.domain.models import Anomaly, Invoice, InvoiceSubmission
from invoiceguard.safety.masking import mask_iban
from invoiceguard.seed import DEMO_UPLOADER, load_master_data, process_demo_invoices

USERS = {
    "alice.uploader": "Alice – AP clerk (uploads invoices)",
    "bob.reviewer": "Bob – AP reviewer",
    "carol.reviewer": "Carol – Finance manager",
}
STATUS_LABELS = {
    InvoiceStatus.PROCESSING: "⏳ Processing",
    InvoiceStatus.AUTO_APPROVED: "✅ Clean – auto-approved",
    InvoiceStatus.FLAGGED: "🚩 Flagged",
    InvoiceStatus.PENDING_REVIEW: "🕒 Pending review",
    InvoiceStatus.APPROVED: "✅ Approved",
    InvoiceStatus.REJECTED: "⛔ Rejected",
    InvoiceStatus.CLARIFICATION_REQUESTED: "✉️ Clarification requested",
}
SEVERITY_ICONS = {Severity.LOW: "🟢", Severity.MEDIUM: "🟡", Severity.HIGH: "🟠",
                  Severity.CRITICAL: "🔴"}
AWAITING = {InvoiceStatus.FLAGGED, InvoiceStatus.PENDING_REVIEW,
            InvoiceStatus.CLARIFICATION_REQUESTED}
FIELD_LABELS = {
    "supplier_name": "Supplier", "supplier_vat_id": "Supplier VAT id",
    "invoice_number": "Invoice number", "invoice_date": "Invoice date", "due_date": "Due date",
    "po_number": "PO number", "currency": "Currency", "subtotal": "Subtotal",
    "vat_amount": "VAT", "total": "Total", "iban": "IBAN",
}


@st.cache_resource
def get_context() -> AppContext:
    ctx = build_context()
    if ctx.settings.storage == "memory":  # quick demo without Docker: seed on start
        load_master_data(ctx.repo, ctx.settings.seed_dir)
        process_demo_invoices(ctx.orchestrator, ctx.settings.invoices_dir, DEMO_UPLOADER)
    return ctx


def _money(value: Decimal | None, currency: str = "") -> str:
    return "—" if value is None else f"{value:,.2f} {currency}".strip()


def _impact(anomalies: list[Anomaly]) -> Decimal:
    return sum((a.monetary_impact for a in anomalies if a.monetary_impact is not None
                and a.monetary_impact > 0), Decimal("0"))


def _ai_label(ctx: AppContext) -> str:
    return "🤖 AI-generated (mock LLM)" if ctx.settings.mode is Mode.MOCK else "🤖 AI-generated"


def _rows(ctx: AppContext) -> list[dict[str, object]]:
    suppliers = {s.id: s.name for s in ctx.repo.list_suppliers()}
    rows: list[dict[str, object]] = []
    for sub in ctx.repo.list_submissions():
        anomalies = ctx.repo.list_anomalies(sub.id)
        invoice = ctx.repo.get_invoice(sub.invoice_id) if sub.invoice_id else None
        if invoice is not None:
            status = STATUS_LABELS[invoice.status]
        elif sub.status.value == "duplicate_rejected":
            status = "⛔ Duplicate – rejected"
        elif sub.status.value == "failed":
            status = "❗ Failed – needs attention"
        else:
            status = f"⏳ {sub.status.value}"
        rows.append({
            "Uploaded": sub.uploaded_at.strftime("%Y-%m-%d %H:%M"),
            "File": sub.filename,
            "Source": invoice.data.source_type.value if invoice else "—",
            "Supplier": suppliers.get(invoice.supplier_id, "?") if invoice else "—",
            "Invoice no.": invoice.data.invoice_number if invoice else "—",
            "Total": _money(invoice.data.total, invoice.data.currency) if invoice else "—",
            "Status": status,
            "Anomalies": len(anomalies),
            "Needs review": ", ".join(invoice.needs_review_fields) if invoice else "",
            "Impact": float(_impact(anomalies)),
        })
    return rows


def page_dashboard(ctx: AppContext) -> None:
    st.header("Invoices")
    rows = _rows(ctx)
    if not rows:
        st.info("No invoices yet. Upload one from the **Upload** page.")
        return
    df = pd.DataFrame(rows)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Submissions", len(df))
    c2.metric("Awaiting decision", int(df["Status"].str.contains("Flagged|Pending").sum()))
    c3.metric("Auto-approved", int(df["Status"].str.contains("auto-approved").sum()))
    c4.metric("Potential impact", f"{df['Impact'].sum():,.2f}")
    f1, f2, f3 = st.columns(3)
    status_filter = f1.multiselect("Status", sorted(df["Status"].unique()))
    supplier_filter = f2.multiselect("Supplier", sorted(df["Supplier"].unique()))
    source_filter = f3.multiselect("Source", sorted(df["Source"].unique()))
    if status_filter:
        df = df[df["Status"].isin(status_filter)]
    if supplier_filter:
        df = df[df["Supplier"].isin(supplier_filter)]
    if source_filter:
        df = df[df["Source"].isin(source_filter)]
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={"Impact": st.column_config.NumberColumn(format="%.2f")})


def page_upload(ctx: AppContext, user: str) -> None:
    st.header("Upload invoice")
    st.caption("Structured e-invoices (FatturaPA, KSeF) are parsed directly. PDFs and scans go "
               "through Document Intelligence"
               + (" (mock mode: only files with a recorded response)." if ctx.settings.mode is
                  Mode.MOCK else "."))
    uploaded = st.file_uploader("Invoice file", type=["xml", "pdf", "png", "jpg", "jpeg", "tif"])
    if uploaded is not None and st.button("Validate", type="primary"):
        sub = ctx.orchestrator.submit(uploaded.getvalue(), uploaded.name, user)
        st.success(f"Submission {sub.id[:8]} – status: {sub.status.value}")
        if sub.failure_reason:
            st.error(sub.failure_reason)


def _render_anomaly(ctx: AppContext, anomaly: Anomaly) -> None:
    title = (f"{SEVERITY_ICONS[anomaly.severity]} {anomaly.severity.value.upper()} · "
             f"{anomaly.type.value}")
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.write(anomaly.message)
        if anomaly.monetary_impact is not None:
            st.caption(f"Monetary impact: {_money(anomaly.monetary_impact)} · detected by "
                       f"{anomaly.detected_by.value}")
        if anomaly.explanation and anomaly.explanation != FALLBACK_TEXT:
            st.info(f"{_ai_label(ctx)} — verify before acting:\n\n{anomaly.explanation}")
        elif anomaly.explanation:
            st.caption(f"🤖 {FALLBACK_TEXT}")
        with st.expander("Evidence"):
            st.json(anomaly.evidence)


def _render_invoice(ctx: AppContext, invoice: Invoice) -> None:
    d = invoice.data
    st.subheader(f"{d.supplier_name} · {d.invoice_number}")
    st.markdown(f"**Status:** {STATUS_LABELS[invoice.status]} · **Source:** {d.source_type.value}")
    threshold = ctx.rules.confidence_threshold
    values = {
        "supplier_name": d.supplier_name, "supplier_vat_id": d.supplier_vat_id,
        "invoice_number": d.invoice_number, "invoice_date": d.invoice_date.isoformat(),
        "due_date": d.due_date.isoformat() if d.due_date else "—",
        "po_number": d.po_number or "—", "currency": d.currency,
        "subtotal": _money(d.subtotal), "vat_amount": _money(d.vat_amount),
        "total": _money(d.total), "iban": mask_iban(d.iban) or "—",
    }
    left, right = st.columns(2)
    with left:
        st.markdown("**Extracted fields**")
        table = []
        for key, value in values.items():
            conf = d.field_confidence.get(key)
            flag = "⚠️ needs review" if conf is not None and conf < threshold else ""
            table.append({"Field": FIELD_LABELS[key], "Value": value,
                          "Confidence": "—" if conf is None else f"{conf:.2f}", "": flag})
        for key, conf in sorted(d.field_confidence.items()):
            if key.startswith("lines."):
                table.append({"Field": f"Lines · {key[6:]} (lowest)", "Value": "",
                              "Confidence": f"{conf:.2f}",
                              "": "⚠️ needs review" if conf < threshold else ""})
        st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
        if invoice.needs_review_fields:
            st.warning(f"Low-confidence fields (< {threshold:.2f}): "
                       f"{', '.join(invoice.needs_review_fields)}. Auto-approval is blocked.")
    with right:
        st.markdown("**Invoice lines**")
        st.dataframe(pd.DataFrame([{
            "#": ln.line_no, "SKU": ln.sku, "Description": ln.description,
            "Qty": str(ln.quantity), "Unit price": str(ln.unit_price),
            "VAT %": str(ln.vat_rate), "Line total": str(ln.line_total),
        } for ln in d.lines]), hide_index=True, use_container_width=True)


def page_detail(ctx: AppContext) -> None:
    st.header("Invoice detail & evidence")
    subs = ctx.repo.list_submissions()
    if not subs:
        st.info("No submissions yet.")
        return
    labels = {f"{s.filename} ({s.status.value})": s for s in subs}
    sub: InvoiceSubmission = labels[st.selectbox("Submission", list(labels))]
    invoice = ctx.repo.get_invoice(sub.invoice_id) if sub.invoice_id else None
    if sub.failure_reason:
        st.error(f"Failed – needs attention: {sub.failure_reason}")
    if sub.duplicate_of_invoice_id:
        st.warning("This file was rejected as a duplicate of an invoice already received.")
    if invoice:
        _render_invoice(ctx, invoice)
    anomalies = sorted(ctx.repo.list_anomalies(sub.id), key=lambda a: -a.severity.rank)
    st.markdown(f"### Anomalies ({len(anomalies)})")
    if not anomalies:
        st.success("No anomalies detected by the deterministic checks.")
    for anomaly in anomalies:
        _render_anomaly(ctx, anomaly)
    run = ctx.repo.get_run(sub.file_sha256)
    if run is not None:
        st.caption(f"Run: {run.status.value} · {run.latency_ms or 0} ms · model "
                   f"{run.model_deployment or '—'} · tokens {run.prompt_tokens}+"
                   f"{run.completion_tokens} · est. cost {run.estimated_cost} "
                   f"{ctx.rules.llm_pricing.currency}")
    with st.expander("Audit trail (masked)"):
        events = ctx.repo.list_audit(submission_id=sub.id)
        st.dataframe(pd.DataFrame([{
            "Time": e.timestamp.strftime("%Y-%m-%d %H:%M:%S"), "Actor": e.actor,
            "Event": e.event_type, "Payload": json.dumps(e.payload),
        } for e in events]), hide_index=True, use_container_width=True)


def _render_email_draft(ctx: AppContext, invoice: Invoice, user: str) -> None:
    draft = ctx.repo.get_email_draft(invoice.id)
    if draft is None:
        return
    st.markdown(f"**Supplier email draft** · {_ai_label(ctx) if draft.generated_by.startswith('llm') else 'manual'}"
                " · *never sent automatically*")
    with st.form(f"draft-{invoice.id}"):
        subject = st.text_input("Subject", value=draft.subject)
        body = st.text_area("Body", value=draft.body, height=200)
        if draft.updated_by:
            st.caption(f"Last edited by {draft.updated_by}")
        if st.form_submit_button("Save draft"):
            try:
                ctx.orchestrator.update_email_draft(invoice.id, user, subject, body)
            except ApprovalError as exc:
                st.error(str(exc))
            else:
                st.success("Draft saved (not sent).")


def page_inbox(ctx: AppContext, user: str) -> None:
    st.header("Approval inbox")
    pending = ctx.repo.list_invoices(AWAITING)
    if not pending:
        st.success("Nothing waiting for a decision. 🎉")
        return
    for invoice in pending:
        sub = ctx.repo.get_submission(invoice.submission_id)
        anomalies = ctx.repo.list_anomalies(invoice.submission_id)
        d = invoice.data
        header = (f"{STATUS_LABELS[invoice.status]} · {d.supplier_name} · {d.invoice_number} · "
                  f"{_money(d.total, d.currency)} · {len(anomalies)} anomal"
                  f"{'y' if len(anomalies) == 1 else 'ies'}")
        with st.expander(header):
            if invoice.reminder_sent_at:
                st.warning("⏰ Waiting longer than the approval timeout – escalated.")
            if invoice.needs_review_fields:
                st.warning(f"Verify these fields against the document: "
                           f"{', '.join(invoice.needs_review_fields)}")
            for anomaly in sorted(anomalies, key=lambda a: -a.severity.rank):
                _render_anomaly(ctx, anomaly)
            _render_email_draft(ctx, invoice, user)
            if sub is not None and sub.uploaded_by == user:
                st.info("You uploaded this invoice, so you cannot decide on it "
                        "(segregation of duties). Switch user in the sidebar.")
                continue
            with st.form(f"decision-{invoice.id}"):
                decision = st.radio("Decision", list(DecisionType), horizontal=True,
                                    format_func=lambda d: d.value.replace("_", " ").title())
                comment = st.text_area("Comment (required to reject or request clarification)")
                if st.form_submit_button("Submit decision", type="primary"):
                    try:
                        ctx.orchestrator.record_decision(invoice.id, user, decision, comment)
                    except ApprovalError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Decision recorded.")
                        st.rerun()


def main() -> None:
    st.set_page_config(page_title="InvoiceGuard AI", page_icon="🛡️", layout="wide")
    ctx = get_context()
    if ctx.settings.mode is Mode.MOCK:
        st.warning("**MOCK MODE** – synthetic data only; no Azure services are called "
                   "(recorded Document Intelligence responses, deterministic mock LLM).",
                   icon="🧪")
    st.sidebar.title("🛡️ InvoiceGuard AI")
    user = st.sidebar.selectbox("Signed in as", list(USERS), format_func=lambda u: USERS[u])
    page = st.sidebar.radio("Page", ["Dashboard", "Upload", "Invoice detail", "Approval inbox"])
    st.sidebar.caption(f"LLM: {ctx.llm_label}")
    st.sidebar.caption("The system recommends; a human decides every payment above the "
                       "threshold.")
    if page == "Dashboard":
        page_dashboard(ctx)
    elif page == "Upload":
        page_upload(ctx, user)
    elif page == "Invoice detail":
        page_detail(ctx)
    else:
        page_inbox(ctx, user)


main()
