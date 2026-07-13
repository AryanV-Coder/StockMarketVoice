import requests
import config

print(config.SERVER_URL)
try:
    resp = requests.get(f"{config.SERVER_URL}/clients/dummy_data/9149342829", timeout=3)
    print(resp.status_code)
except Exception as e:
    print(f"Exception: {e}")
