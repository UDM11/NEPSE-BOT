"""Discover Naasa X order page selectors."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from broker.naasa import NaasaBrokerClient
from core.events import EventBus


async def main() -> None:
    bus = EventBus()
    client = NaasaBrokerClient(bus, profile_name="naasa")
    await client.initialize()
    await client.login()
    page = client._page
    assert page

    order_url = "https://x.naasasecurities.com.np/MarketOrder/Order"
    await page.goto(order_url, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(3)

    print("URL:", page.url)
    inputs = await page.eval_on_selector_all(
        "input, select, textarea",
        """els => els.map(e => ({
            tag: e.tagName, type: e.type, id: e.id, name: e.name,
            placeholder: e.placeholder, className: e.className
        }))""",
    )
    buttons = await page.eval_on_selector_all(
        "button, input[type=button], input[type=submit]",
        """els => els.map(e => ({
            text: (e.innerText || e.value || '').trim().slice(0, 50),
            id: e.id, type: e.type, className: e.className
        }))""",
    )
    print("INPUTS:", json.dumps(inputs, indent=2))
    print("BUTTONS:", json.dumps([b for b in buttons if b.get("text")], indent=2))
    await client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
