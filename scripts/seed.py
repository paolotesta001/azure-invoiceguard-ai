"""Seed master data and optionally process the demo invoices.

Usage: python scripts/seed.py [--process-demo]
"""

import argparse
import logging

from invoiceguard.bootstrap import build_context
from invoiceguard.seed import load_master_data, process_demo_invoices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process-demo", action="store_true",
                        help="submit every file in INVOICEGUARD_INVOICES_DIR as alice.uploader")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    ctx = build_context()
    logging.info("master data: %s", load_master_data(ctx.repo, ctx.settings.seed_dir))
    if args.process_demo:
        count = process_demo_invoices(ctx.orchestrator, ctx.settings.invoices_dir)
        logging.info("demo invoices submitted: %d", count)


if __name__ == "__main__":
    main()
