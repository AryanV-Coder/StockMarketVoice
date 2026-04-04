"""
Quick test script to trigger an outbound call.
Usage: python test_call.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SERVER_URL = os.getenv("SERVER_URL")
PHONE_NUMBER = os.getenv("TEST_PHONE_NUMBER")


def main():
    print(f"📞 Calling +91 {PHONE_NUMBER} ...")
    response = requests.post(
        f"{SERVER_URL}/call",
        data={"phone_number": PHONE_NUMBER},
    )
    print(f"Response: {response.json()}")


if __name__ == "__main__":
    main()
