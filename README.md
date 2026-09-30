# Hot Wallet Bot

Posts Coinhako's hot wallet balances to Slack once a day.

## How it runs

- An external cron job calls GitHub's workflow-dispatch API every day at 6:00 PM SGT.
- That starts `.github/workflows/post.yml`, which runs `wallet_report.py`.
- The script fetches each balance from public blockchain APIs and posts one table to Slack.
- To run it by hand: **Actions** → **Post Wallet Balances to Slack** → **Run workflow**.

## Assets tracked

BTC, ETH, SOL, LTC, XRP, XLM, USDT (ERC-20), USDC (ERC-20), USDS, BCH, DOGE

## Files

| File | Purpose |
|---|---|
| `wallet_report.py` | Fetches balances and posts to Slack |
| `.github/workflows/post.yml` | Runs the script on GitHub Actions |

## Secrets

| Secret | Used for |
|---|---|
| `SLACK_WEBHOOK_URL` | Slack channel the report posts to |

## Common changes

- **Change an address:** edit the `ADDR` block near the bottom of `wallet_report.py`.
- **Remove an asset:** remove it from `ADDR`, its `safe_run(...)` line in `main()`, and the `order` list. Missing any one of these crashes the run.
- **Add an ERC-20 token:** add its contract and decimals to `ERC20`, then add its symbol to `order`.

## If something looks wrong

- **No Slack post:** check the cron job's log, then the **Actions** tab.
- **One asset shows `ERROR`:** all of its data sources failed that run. The reason is listed under the table. It usually clears on the next run.

Full details are in the Wallet Balance Bots handover document.
