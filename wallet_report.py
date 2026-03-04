import os
import requests

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

def post_to_slack(text: str):
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=20)
    r.raise_for_status()

def main():
    msg = "Wallet bot test message 🚀"
    post_to_slack(msg)

if __name__ == "__main__":
    main()
