"""
Test script to initiate a call for a single person.
Takes phone number and name as console input.
"""

import requests
import config

BASE_URL = config.SERVER_URL


def fetch_stock_data(phone_number: str) -> dict | None:
    """Fetch stock data for a client from the dummy_data endpoint."""
    try:
        response = requests.get(f"{BASE_URL}/clients/dummy_data/{phone_number}")
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            print(f"✅ Fetched stock data: {len(data['rows'])} rows")
            return {"columns": data["columns"], "rows": data["rows"]}
        else:
            print("❌ No stock data found")
            return None
    except Exception as e:
        print(f"❌ Error fetching stock data: {e}")
        return None


def initiate_call(phone_number: str, client_name: str, stock_data: dict) -> str | None:
    """Atomically register context and initiate call via /initiate-call."""
    try:
        response = requests.post(
            f"{BASE_URL}/initiate-call",
            json={
                "phone_number": phone_number,
                "client_name": client_name,
                "stock_data": stock_data,
            },
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            print(f"✅ Call initiated | SID: {data['call_sid']}")
            return data["call_sid"]
        else:
            print(f"❌ Call failed: {data.get('message')}")
            return None
    except Exception as e:
        print(f"❌ Error initiating call: {e}")
        return None


if __name__ == "__main__":
    print("=" * 50)
    print("📞 StockMarketVoice — Single Call Test")
    print("=" * 50)

    phone_number = input("Enter phone number: ").strip()
    client_name = input("Enter client name: ").strip()

    # 1. Fetch stock data
    stock_data = fetch_stock_data(phone_number)
    if not stock_data or len(stock_data["rows"]) == 0:
        print("❌ No stock data found. Exiting.")
        exit(1)

    print(f"\n📊 Columns: {stock_data['columns']}")
    print(f"📊 Rows: {stock_data['rows']}\n")

    # 2. Initiate call (context is registered atomically on the server)
    initiate_call(phone_number, client_name, stock_data)
