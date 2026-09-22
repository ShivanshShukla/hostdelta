#!/usr/bin/env python3
"""Attach JsonFormatter to the standard logging module.

Writes one JSON object per line to stdout. Point an existing application
log source at this stream (for example by redirecting stdout to a file
listed under application_logs) or copy the handler setup into your app.
"""
import logging
import sys

from hostdelta.telemetry import JsonFormatter


def main() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter("inventory-worker", environment="development", version="0.0.0")
    )
    logger = logging.getLogger("inventory-worker")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info(
        "Synthetic stock check completed",
        extra={
            "event_name": "inventory.stock.checked",
            "attributes": {"sku": "demo-widget", "available": 12},
        },
    )


if __name__ == "__main__":
    main()
