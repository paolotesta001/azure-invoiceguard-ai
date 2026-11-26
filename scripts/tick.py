"""Send approval reminders for invoices waiting longer than the timeout (run periodically)."""

import logging

from invoiceguard.bootstrap import build_context


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    reminded = build_context().orchestrator.check_timeouts()
    logging.info("reminders sent: %d", len(reminded))


if __name__ == "__main__":
    main()
