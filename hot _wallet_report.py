import os
import requests

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

def post_to_slack(text: str):
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=20)
    r.raise_for_status()

def main():
    # Replace these lines with your computed balances later
    lines = [
        "BTC 9.47487",
        "ETH 262.1918",
        "SOL 666.8788",
        "LTC 1,437.084",
        "XRP 403,821.2",
        "XLM 322,559.5",
        "USDT 639,515.9",
        "USDC 330,836.6",
        "BCH 100.5669",
        "DOGE 881,116.2",
    ]

    msg = "*Wallet balances*\n```" + "\n".join(lines) + "```"
    post_to_slack(msg)

if __name__ == "__main__":
    main()
