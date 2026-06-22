"""Discover Naasa X DOM selectors after manual login (headed mode).

Usage:
    BROKER_HEADLESS=false python scripts/discover_naasa_selectors.py

Logs in (or uses saved session), navigates the UI, and prints
input/button elements plus a network analysis report.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from broker.naasa import NaasaBrokerClient
from core.events import EventBus
from core.logging_config import setup_logging


async def discover() -> None:
    setup_logging()
    bus = EventBus()
    client = NaasaBrokerClient(bus, profile_name="naasa")

    await client.initialize()
    try:
        await client.login()
        page = client._page
        assert page

        print("\n=== CURRENT URL ===")
        print(page.url)

        print("\n=== INPUTS ===")
        inputs = await page.eval_on_selector_all(
            "input, select, textarea",
            "els => els.map(e => ({tag: e.tagName, type: e.type, name: e.name, "
            "id: e.id, placeholder: e.placeholder, className: e.className}))",
        )
        print(json.dumps(inputs, indent=2))

        print("\n=== BUTTONS ===")
        buttons = await page.eval_on_selector_all(
            "button, input[type=submit]",
            "els => els.map(e => ({text: e.innerText?.trim(), type: e.type, "
            "id: e.id, className: e.className}))",
        )
        print(json.dumps(buttons, indent=2))

        print("\n=== NAV LINKS ===")
        links = await page.eval_on_selector_all(
            "a, [role=tab], [role=menuitem]",
            "els => els.map(e => ({text: e.innerText?.trim().slice(0,50), href: e.href}))",
        )
        print(json.dumps(links[:30], indent=2))

        report_path = await client.generate_network_report()
        print(f"\n=== NETWORK REPORT SAVED ===\n{report_path}")

    finally:
        await client.shutdown()


if __name__ == "__main__":
    asyncio.run(discover())
