import os
import time
import requests

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

HEADERS = {"User-Agent": "Mozilla/5.0 (WalletBot/1.0)"}
SATOSHI_PER_BTC = 100_000_000

# ================= Slack =================
def post_to_slack(text: str):
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=20)
    r.raise_for_status()

# ================= Helpers =================
def safe_get(url, timeout=25):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r

def safe_get_json(url, timeout=25):
    return safe_get(url, timeout=timeout).json()

def safe_post_json(url, payload, timeout=25):
    r = requests.post(url, json=payload, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()

# ================= BTC (Blockstream) =================
def get_btc_balance(address: str) -> float:
    data = safe_get_json(f"https://blockstream.info/api/address/{address}")
    funded = data["chain_stats"]["funded_txo_sum"]
    spent = data["chain_stats"]["spent_txo_sum"]
    return (funded - spent) / SATOSHI_PER_BTC

# ================= ETH + ERC20 (RPC fallback) =================
ETH_RPCS = [
    "https://cloudflare-eth.com",
    "https://ethereum.publicnode.com",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
]

def eth_rpc_call(method: str, params: list):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    last_err = None
    for rpc in ETH_RPCS:
        try:
            out = safe_post_json(rpc, payload, timeout=25)
            if "error" in out:
                last_err = out["error"]
                time.sleep(0.25)
                continue
            return out["result"]
        except Exception as e:
            last_err = str(e)
            time.sleep(0.25)
    raise RuntimeError(f"All ETH RPCs failed. Last error: {last_err}")

def get_eth_balance(address: str) -> float:
    bal_hex = eth_rpc_call("eth_getBalance", [address, "latest"])
    return int(bal_hex, 16) / 1e18

def get_erc20_balance(address: str, contract: str, decimals: int) -> float:
    selector = "0x70a08231"
    padded_addr = address.lower().replace("0x", "").rjust(64, "0")
    data = selector + padded_addr
    res = eth_rpc_call("eth_call", [{"to": contract, "data": data}, "latest"])
    return int(res, 16) / (10 ** decimals)

# ================= SOL (Solana RPC) =================
def get_sol_balance(address: str) -> float:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
    out = safe_post_json("https://api.mainnet-beta.solana.com", payload, timeout=25)
    return out["result"]["value"] / 1e9

# ================= SPL Tokens (Solana) =================
SOLANA_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-mainnet.g.alchemy.com/v2/demo",
]

def sol_rpc_call(payload: dict):
    last_err = None
    for rpc in SOLANA_RPCS:
        try:
            out = safe_post_json(rpc, payload, timeout=25)
            if "error" in out:
                last_err = out["error"]
                time.sleep(0.25)
                continue
            return out
        except Exception as e:
            last_err = str(e)
            time.sleep(0.25)
    raise RuntimeError(f"All SOL RPCs failed. Last error: {last_err}")

def get_spl_token_balance(owner: str, mint: str) -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            owner,
            {"mint": mint},
            {"encoding": "jsonParsed"}
        ]
    }

    out = sol_rpc_call(payload)

    total = 0.0
    for acc in out["result"]["value"]:
        token_amount = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
        total += float(token_amount["uiAmount"] or 0.0)

    return total

# ================= LTC / DOGE (BlockCypher) =================
def get_blockcypher_balance(symbol: str, address: str) -> float:
    data = safe_get_json(f"https://api.blockcypher.com/v1/{symbol}/main/addrs/{address}/balance")
    return data["final_balance"] / SATOSHI_PER_BTC

# ================= XRP (XRPL RPC) =================
def get_xrp_balance(address: str) -> float:
    payload = {"method": "account_info", "params": [{"account": address, "ledger_index": "validated"}]}
    out = safe_post_json("https://s2.ripple.com:51234", payload, timeout=25)
    bal_drops = out["result"]["account_data"]["Balance"]
    return int(bal_drops) / 1_000_000

# ================= XLM (Horizon) =================
def get_xlm_balance(address: str) -> float:
    data = safe_get_json(f"https://horizon.stellar.org/accounts/{address}")
    for b in data.get("balances", []):
        if b.get("asset_type") == "native":
            return float(b["balance"])
    return 0.0

# ================= BCH =================
def get_bch_balance(address: str) -> float:
    cashaddr = address.replace("bitcoincash:", "")
    candidates = [cashaddr, f"bitcoincash:{cashaddr}"]

    last = None
    for a in candidates:
        url = f"https://bch.fullstack.cash/v6/fulcrum/balance/{a}"
        r = safe_get(url, timeout=25)
        j = r.json()
        last = j

        if isinstance(j, dict) and "confirmed" in j:
            return int(j["confirmed"]) / SATOSHI_PER_BTC
        if isinstance(j, dict) and "balance" in j and "confirmed" in j["balance"]:
            return int(j["balance"]["confirmed"]) / SATOSHI_PER_BTC

    raise RuntimeError(f"Unexpected BCH response: {last}")

# ================= TRON / TRC20 =================
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58decode_check(s: str) -> bytes:
    num = 0
    for char in s:
        num = num * 58 + B58_ALPHABET.index(char)
    combined = num.to_bytes((num.bit_length() + 7) // 8, byteorder="big")

    # restore leading zero bytes
    n_pad = 0
    for c in s:
        if c == "1":
            n_pad += 1
        else:
            break
    combined = b"\x00" * n_pad + combined

    # strip 4-byte checksum
    return combined[:-4]

def tron_base58_to_hex(addr: str) -> str:
    return b58decode_check(addr).hex()

def get_trc20_balance(address: str, contract: str, decimals: int) -> float:
    owner_hex = tron_base58_to_hex(address)
    contract_hex = tron_base58_to_hex(contract)

    payload = {
        "owner_address": owner_hex,
        "contract_address": contract_hex,
        "function_selector": "balanceOf(address)",
        "parameter": owner_hex[2:].rjust(64, "0"),
        "visible": False
    }

    out = safe_post_json(
        "https://api.trongrid.io/wallet/triggerconstantcontract",
        payload,
        timeout=25
    )

    result = out.get("constant_result", [])
    if not result:
        raise RuntimeError(f"Unexpected TRON response: {out}")

    raw = int(result[0], 16)
    return raw / (10 ** decimals)

# ================= Addresses =================
ADDR = {
    "BTC": "14dJRoKyj2i83uRbTUeKqhFMwvFZcpiXyn",
    "ETH": "0xd4BDDf5E3D0435D7A6214A0B949C7BB58621F37C",
    "SOL": "FLgJwoX3pPye21UuenU9urrSHRZTNCX8R6fsfSfCX5T9",
    "LTC": "LehGWLyxu6UHG81Ue7XNoHSJnJ4uDkQkHb",
    "DOGE": "DJ7DymrXjniEdR5hhgTifoVn6NSWJySAvr",
    "BCH": "bitcoincash:qrhzxk90l59ryl08sxcsxjnrg8j6awsxq5xnwhvp44",
    "XRP": "r4ep6pSY9JhMhLHGFb5GtVabzS1KvihiZP",
    "XLM": "GBFVU7QY6EMTYSF3WKH54CO5CE46BC72HOKZBBXH5YBJBLDVT3RNSNM2",
    
}

ERC20 = {
    "USDT(ERC)": {"contract": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
    "USDC(ERC)": {"contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    "USDS": {"contract": "0xdC035D45d973E3EC169d2276DDab16f1e407384F", "decimals": 18},
    
}


# ================= Main =================
def main():
    results = {}

    def safe_run(symbol, fn):
        try:
            results[symbol] = fn()
        except Exception:
            results[symbol] = 0.0

    safe_run("BTC", lambda: get_btc_balance(ADDR["BTC"]))
    safe_run("ETH", lambda: get_eth_balance(ADDR["ETH"]))
    safe_run("SOL", lambda: get_sol_balance(ADDR["SOL"]))
    safe_run("LTC", lambda: get_blockcypher_balance("ltc", ADDR["LTC"]))
    safe_run("XRP", lambda: get_xrp_balance(ADDR["XRP"]))
    safe_run("XLM", lambda: get_xlm_balance(ADDR["XLM"]))
    safe_run("BCH", lambda: get_bch_balance(ADDR["BCH"]))
    safe_run("DOGE", lambda: get_blockcypher_balance("doge", ADDR["DOGE"]))

    for sym, meta in ERC20.items():
        safe_run(sym, lambda m=meta: get_erc20_balance(ADDR["ETH"], m["contract"], m["decimals"]))

    order = [
        "BTC",
        "ETH",
        "SOL",
        "LTC",
        "XRP",
        "XLM",
        "USDT(ERC)",
        "USDC(ERC)",
        "USDS",
        "BCH",
        "DOGE"
    ]

    lines = [f"{t:<10} {results[t]:>15,.4f}" for t in order]

    msg = "*Hot wallet balances*\n```" + "\n".join(lines) + "```"
    post_to_slack(msg)

if __name__ == "__main__":
    main()
