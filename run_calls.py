"""
Main orchestrator script to run on the server.

Flow:
1. Fetch all clients from the /clients/ endpoint
2. For each client, retrieve their stock data from /clients/dummy_data/{phone_number}
3. Initiate a call to each client one by one
4. The stock data (columns + rows) is stored in memory and injected into the
   conversation when the call's media stream connects.
"""

import requests
import time
import config

# The base URL of the running FastAPI server
BASE_URL = config.SERVER_URL


def fetch_all_clients() -> list[dict]:
    """Fetch all clients from the /clients/ endpoint."""
    try:
        response = requests.get(f"{BASE_URL}/clients/")
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            print(f"✅ Fetched {len(data['data'])} clients")
            return data["data"]
        else:
            print("❌ Failed to fetch clients")
            return []
    except Exception as e:
        print(f"❌ Error fetching clients: {e}")
        return []


def fetch_client_stock_data(phone_number: int) -> dict | None:
    """Fetch stock data for a client from the /clients/dummy_data/{phone_number} endpoint."""
    try:
        response = requests.get(f"{BASE_URL}/clients/dummy_data/{phone_number}")
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            print(f"✅ Fetched stock data for {phone_number}: {len(data['rows'])} rows")
            return {"columns": data["columns"], "rows": data["rows"]}
        else:
            print(f"❌ No stock data found for {phone_number}")
            return None
    except Exception as e:
        print(f"❌ Error fetching stock data for {phone_number}: {e}")
        return None


def initiate_call(phone_number: str) -> str | None:
    """Initiate a call to a client via the /call endpoint."""
    try:
        response = requests.post(f"{BASE_URL}/call", data={"phone_number": phone_number})
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            print(f"✅ Call initiated to {phone_number} | SID: {data['call_sid']}")
            return data["call_sid"]
        else:
            print(f"❌ Failed to initiate call to {phone_number}: {data.get('message')}")
            return None
    except Exception as e:
        print(f"❌ Error initiating call to {phone_number}: {e}")
        return None


def register_call_context(phone_number: str, client_name: str, stock_data: dict) -> bool:
    """Register the stock data context for an upcoming call on the server."""
    try:
        response = requests.post(
            f"{BASE_URL}/register-call-context",
            json={
                "phone_number": phone_number,
                "client_name": client_name,
                "stock_data": stock_data,
            },
        )
        response.raise_for_status()
        print(f"✅ Registered call context for {client_name} ({phone_number})")
        return True
    except Exception as e:
        print(f"❌ Error registering call context for {phone_number}: {e}")
        return False


def run():
    """Main orchestration loop."""
    print("=" * 60)
    print("📞 StockMarketVoice — Call Orchestrator")
    print("=" * 60)

    # 1. Fetch all clients
    clients = fetch_all_clients()
    if not clients:
        print("❌ No clients found. Exiting.")
        return

    print(f"\n📋 Processing {len(clients)} clients...\n")

    for i, client in enumerate(clients, 1):
        client_name = client["name"]
        phone_number = client["phone_number"]

        print(f"\n--- Client {i}/{len(clients)}: {client_name} ({phone_number}) ---")

        # 2. Fetch stock data for this client
        stock_data = fetch_client_stock_data(phone_number)
        if not stock_data or len(stock_data["rows"]) == 0:
            print(f"⚠ No stock data for {client_name}. Skipping.")
            continue

        # 3. Register the stock context on the server before calling
        registered = register_call_context(str(phone_number), client_name, stock_data)
        if not registered:
            print(f"⚠ Could not register context for {client_name}. Skipping.")
            continue

        # 4. Initiate the call
        call_sid = initiate_call(str(phone_number))
        if not call_sid:
            print(f"⚠ Call failed for {client_name}. Moving to next client.")
            continue

        # # 5. Wait before calling the next client (avoid overlapping calls)
        # if i < len(clients):
        #     wait_time = 120  # seconds — adjust based on expected call duration
        #     print(f"⏳ Waiting {wait_time}s before next call...")
        #     time.sleep(wait_time)

    print("\n" + "=" * 60)
    print("✅ All clients processed.")
    print("=" * 60)


if __name__ == "__main__":
    run()