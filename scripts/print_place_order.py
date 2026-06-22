"""Extract PlaceOrder JS function source code from Naasa X."""

import asyncio
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
    await asyncio.sleep(2)

    print("=== JS FUNCTION PlaceOrder ===")
    source = await page.evaluate("typeof PlaceOrder !== 'undefined' ? PlaceOrder.toString() : 'PlaceOrder is undefined'")
    print(source)

    print("\n=== JS FUNCTION ExecuteOrderRequest ===")
    source2 = await page.evaluate("typeof ExecuteOrderRequest !== 'undefined' ? ExecuteOrderRequest.toString() : 'ExecuteOrderRequest is undefined'")
    print(source2)

    print("\n=== JS FUNCTION ExecuteAPI ===")
    source3 = await page.evaluate("typeof ExecuteAPI !== 'undefined' ? ExecuteAPI.toString() : 'ExecuteAPI is undefined'")
    print(source3)

    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
