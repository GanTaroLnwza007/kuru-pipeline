"""Check OpenRouter account balance and usage.

Usage:
    uv run kuru-cost

Note: /api/v1/credits returns account-level totals only.
Per-key breakdown requires an account-level key — view it at:
https://openrouter.ai/settings/keys
"""

import json
import os
import sys
import urllib.request

from dotenv import load_dotenv

load_dotenv()


def _get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set in .env")
        sys.exit(1)

    key_preview = api_key[:12] + "..." + api_key[-4:]
    print(f"Key : {key_preview}")
    print()

    try:
        data = _get("https://openrouter.ai/api/v1/credits", api_key).get("data", {})
        total_credits = float(data.get("total_credits", 0))
        total_usage   = float(data.get("total_usage", 0))
        remaining     = total_credits - total_usage

        print("=== OpenRouter Account (all keys combined) ===")
        print(f"  Total credits added : ${total_credits:.4f}")
        print(f"  Total spent         : ${total_usage:.4f}")
        print(f"  Remaining           : ${remaining:.4f}")
        print()
        print("  Per-key breakdown -> https://openrouter.ai/settings/keys")
    except Exception as exc:
        print(f"  Failed to fetch credits: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
