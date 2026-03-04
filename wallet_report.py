def main():
    # build lines from your results dict (you already have this logic in Colab)
    # Example output format:
    lines = [
        f"BTC {results['BTC']:,.4f}",
        f"ETH {results['ETH']:,.4f}",
        f"SOL {results['SOL']:,.4f}",
        f"LTC {results['LTC']:,.4f}",
        f"XRP {results['XRP']:,.4f}",
        f"XLM {results['XLM']:,.4f}",
        f"USDT {results['USDT']:,.4f}",
        f"USDC {results['USDC']:,.4f}",
        f"DAI {results['DAI']:,.4f}",
        f"BCH {results['BCH']:,.4f}",
        f"DOGE {results['DOGE']:,.4f}",
    ]

    msg = "*Hot wallet update*\n```" + "\n".join(lines) + "```"
    post_to_slack(msg)
