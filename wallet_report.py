
# Two changes from your original:
# 1. LTC now uses litecoinspace.org instead of BlockCypher (which rate-limits and silently fails)
# 2. Errors are posted to Slack instead of only printed to stdout

import os
import time
import hashlib
import json
import socket
import ssl
import requests

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

HEADERS = {"User-Agent": "Mozilla/5.0 (WalletBot/1.0)"}
SATOSHI_PER_BTC = 100_000_000

# ── Helpers ──────────────────────────────────────────────────────────────────

def post_to_slack(text: str):
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=20)
    r.raise_for_status()

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

# ── BTC ──────────────────────────────────────────────────────────────────────

def get_btc_balance(address: str) -> float:
    """
    Tries three BTC APIs in order:
      1. blockstream.info  – original, preferred
      2. Blockchair        – reliable free tier, same satoshi structure
      3. mempool.space     – final fallback, identical API shape to blockstream
    """
    # 1. blockstream.info (original)
    try:
        data = safe_get_json(f"https://blockstream.info/api/address/{address}")
        funded = data["chain_stats"]["funded_txo_sum"]
        spent  = data["chain_stats"]["spent_txo_sum"]
        return (funded - spent) / SATOSHI_PER_BTC
    except Exception:
        pass

    # 2. Blockchair
    try:
        data = safe_get_json(f"https://api.blockchair.com/bitcoin/dashboards/address/{address}")
        satoshis = data["data"][address]["address"]["balance"]
        return satoshis / SATOSHI_PER_BTC
    except Exception:
        pass

    # 3. mempool.space — identical JSON shape to blockstream
    data = safe_get_json(f"https://mempool.space/api/address/{address}")
    funded = data["chain_stats"]["funded_txo_sum"]
    spent  = data["chain_stats"]["spent_txo_sum"]
    return (funded - spent) / SATOSHI_PER_BTC

# ── ETH / ERC-20 ─────────────────────────────────────────────────────────────

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

# ── SOL / SPL ─────────────────────────────────────────────────────────────────

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

def get_sol_balance(address: str) -> float:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
    out = sol_rpc_call(payload)
    return out["result"]["value"] / 1e9

def get_spl_token_balance(owner: str, mint: str) -> float:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [owner, {"mint": mint}, {"encoding": "jsonParsed"}]
    }
    out = sol_rpc_call(payload)
    total = 0.0
    for acc in out["result"]["value"]:
        token_amount = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
        total += float(token_amount["uiAmount"] or 0.0)
    return total

# ── LTC (multi-source fallback) ───────────────────────────────────────────────

def get_ltc_balance(address: str) -> float:
    """
    Tries three LTC APIs in order:
      1. litecoinspace.org  – same structure as blockstream (preferred)
      2. Blockchair         – reliable, generous free tier
      3. BlockCypher        – last resort; rate-limits under high call volume
    """
    # 1. litecoinspace.org (original)
    try:
        data = safe_get_json(f"https://litecoinspace.org/api/address/{address}")
        funded = data["chain_stats"]["funded_txo_sum"]
        spent  = data["chain_stats"]["spent_txo_sum"]
        return (funded - spent) / SATOSHI_PER_BTC
    except Exception:
        pass

    # 2. Blockchair — returns balance in litoshis under data[addr].address.balance
    try:
        data = safe_get_json(f"https://api.blockchair.com/litecoin/dashboards/address/{address}")
        litoshis = data["data"][address]["address"]["balance"]
        return litoshis / SATOSHI_PER_BTC
    except Exception:
        pass

    # 3. BlockCypher — already used for DOGE; fine as an occasional fallback
    return get_blockcypher_balance("ltc", address)

# ── DOGE (BlockCypher kept — only one call, less likely to be rate-limited) ───

def get_blockcypher_balance(symbol: str, address: str) -> float:
    data = safe_get_json(f"https://api.blockcypher.com/v1/{symbol}/main/addrs/{address}/balance")
    return data["final_balance"] / SATOSHI_PER_BTC

# ── XRP ──────────────────────────────────────────────────────────────────────

def get_xrp_balance(address: str) -> float:
    payload = {"method": "account_info", "params": [{"account": address, "ledger_index": "validated"}]}
    out = safe_post_json("https://s2.ripple.com:51234", payload, timeout=25)
    bal_drops = out["result"]["account_data"]["Balance"]
    return int(bal_drops) / 1_000_000

# ── XLM ──────────────────────────────────────────────────────────────────────

def get_xlm_balance(address: str) -> float:
    data = safe_get_json(f"https://horizon.stellar.org/accounts/{address}")
    for b in data.get("balances", []):
        if b.get("asset_type") == "native":
            return float(b["balance"])
    return 0.0

# ── BCH ──────────────────────────────────────────────────────────────────────

CASHADDR_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def _polymod(values):
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07ffffffff) << 5) ^ d
        if c0 & 0x01: c ^= 0x98f2bc8e61
        if c0 & 0x02: c ^= 0x79b76d99e2
        if c0 & 0x04: c ^= 0xf33e5fb3c4
        if c0 & 0x08: c ^= 0xae2eabe2a8
        if c0 & 0x10: c ^= 0x1e4f43e470
    return c ^ 1

def _convertbits(data, frombits, tobits, pad=True):
    acc, bits, ret = 0, 0, []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret

def cashaddr_to_hash160(addr: str) -> bytes:
    prefix = "bitcoincash"
    payload_str = addr.split(":")[-1].lower()
    payload = [CASHADDR_CHARSET.index(c) for c in payload_str]
    check_input = [ord(x) & 0x1f for x in prefix] + [0] + payload
    if _polymod(check_input) != 0:
        raise ValueError("Bad CashAddr checksum")
    data = _convertbits(payload[:-8], 5, 8, False)
    return bytes(data[1:])  # drop version byte, keep hash160

def bch_scripthash(hash160: bytes) -> str:
    script = bytes([0x76, 0xa9, 0x14]) + hash160 + bytes([0x88, 0xac])  # P2PKH
    digest = hashlib.sha256(script).digest()
    return digest[::-1].hex()  # Electrum protocol wants byte-reversed hex

ELECTRUM_SERVERS = [
    ("electrum.imaginary.cash", 50002),
    ("bch.loping.net", 50002),
    ("electroncash.dk", 50002),
]

def electrum_request(scripthash: str) -> dict:
    payload = json.dumps({
        "id": 1, "method": "blockchain.scripthash.get_balance", "params": [scripthash]
    }) + "\n"
    last_err = None
    for host, port in ELECTRUM_SERVERS:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    ssock.sendall(payload.encode())
                    data = b""
                    while not data.endswith(b"\n"):
                        chunk = ssock.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    return json.loads(data.decode())
        except Exception as e:
            last_err = str(e)
    raise RuntimeError(f"All Electrum servers failed. Last error: {last_err}")

def get_bch_balance_electrum(address: str) -> float:
    hash160 = cashaddr_to_hash160(address)
    scripthash = bch_scripthash(hash160)
    out = electrum_request(scripthash)
    result = out.get("result")
    if result is None:
        raise RuntimeError(f"Unexpected Electrum response: {out}")
    return (result["confirmed"] + result["unconfirmed"]) / SATOSHI_PER_BTC

def get_bch_balance(address: str) -> float:
    """
    Tries three BCH sources in order:
      1. Electrum-Cash protocol – direct socket, no key, no HTTP rate limits
      2. Blockchair              – may 430 on shared CI IPs
      3. api.haskoin.com         – last resort; currently 404ing
    """
    addr = address.replace("bitcoincash:", "")
    errs = []

    try:
        return get_bch_balance_electrum(address)
    except Exception as e:
        errs.append(f"Electrum: {e}")

    try:
        data = safe_get_json(f"https://api.blockchair.com/bitcoin-cash/dashboards/address/{addr}")
        satoshis = data["data"][addr]["address"]["balance"]
        return satoshis / SATOSHI_PER_BTC
    except Exception as e:
        errs.append(f"Blockchair: {e}")

    try:
        data = safe_get_json(f"https://api.haskoin.com/bch/address/{addr}/balance")
        return data["confirmed"] / SATOSHI_PER_BTC
    except Exception as e:
        errs.append(f"Haskoin: {e}")

    raise RuntimeError(" | ".join(errs))
# ── TRON / TRC-20 ────────────────────────────────────────────────────────────

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58decode_check(s: str) -> bytes:
    num = 0
    for char in s:
        num = num * 58 + B58_ALPHABET.index(char)
    combined = num.to_bytes((num.bit_length() + 7) // 8, byteorder="big")
    n_pad = 0
    for c in s:
        if c == "1":
            n_pad += 1
        else:
            break
    combined = b"\x00" * n_pad + combined
    return combined[:-4]

def tron_base58_to_hex(addr: str) -> str:
    return b58decode_check(addr).hex()

def get_trc20_balance(address: str, contract: str, decimals: int) -> float:
    owner_hex    = tron_base58_to_hex(address)
    contract_hex = tron_base58_to_hex(contract)
    payload = {
        "owner_address":    owner_hex,
        "contract_address": contract_hex,
        "function_selector": "balanceOf(address)",
        "parameter": owner_hex[2:].rjust(64, "0"),
        "visible": False
    }
    out = safe_post_json("https://api.trongrid.io/wallet/triggerconstantcontract", payload, timeout=25)
    result = out.get("constant_result", [])
    if not result:
        raise RuntimeError(f"Unexpected TRON response: {out}")
    return int(result[0], 16) / (10 ** decimals)

# ── Addresses & tokens ───────────────────────────────────────────────────────

ADDR = {
    "BTC":  "14dJRoKyj2i83uRbTUeKqhFMwvFZcpiXyn",
    "ETH":  "0xd4BDDf5E3D0435D7A6214A0B949C7BB58621F37C",
    "SOL":  "FLgJwoX3pPye21UuenU9urrSHRZTNCX8R6fsfSfCX5T9",
    "LTC":  "LehGWLyxu6UHG81Ue7XNoHSJnJ4uDkQkHb",
    "DOGE": "DJ7DymrXjniEdR5hhgTifoVn6NSWJySAvr",
    "BCH":  "bitcoincash:qrhzxk90l59ryl08sxcsxjnrg8j6awsxq5xnwhvp44",
    "XRP":  "r4ep6pSY9JhMhLHGFb5GtVabzS1KvihiZP",
    "XLM":  "GBFVU7QY6EMTYSF3WKH54CO5CE46BC72HOKZBBXH5YBJBLDVT3RNSNM2",
}

ERC20 = {
    "USDT(ERC)": {"contract": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
    "USDC(ERC)": {"contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    "USDS":      {"contract": "0xdC035D45d973E3EC169d2276DDab16f1e407384F", "decimals": 18},
}

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    results = {}
    errors  = {}

    def safe_run(symbol, fn):
        try:
            results[symbol] = fn()
        except Exception as e:
            results[symbol] = None
            errors[symbol]  = str(e)

    safe_run("BTC",  lambda: get_btc_balance(ADDR["BTC"]))
    safe_run("ETH",  lambda: get_eth_balance(ADDR["ETH"]))
    safe_run("SOL",  lambda: get_sol_balance(ADDR["SOL"]))
    safe_run("LTC",  lambda: get_ltc_balance(ADDR["LTC"]))  # ← changed
    safe_run("XRP",  lambda: get_xrp_balance(ADDR["XRP"]))
    safe_run("XLM",  lambda: get_xlm_balance(ADDR["XLM"]))
    safe_run("BCH",  lambda: get_bch_balance(ADDR["BCH"]))
    safe_run("DOGE", lambda: get_blockcypher_balance("doge", ADDR["DOGE"]))

    for sym, meta in ERC20.items():
        safe_run(sym, lambda m=meta: get_erc20_balance(ADDR["ETH"], m["contract"], m["decimals"]))

    order = ["BTC", "ETH", "SOL", "LTC", "XRP", "XLM", "USDT(ERC)", "USDC(ERC)", "USDS", "BCH", "DOGE"]
    lines = [
        f"{t:<12} {'ERROR':>15}"        if results[t] is None else
        f"{t:<12} {results[t]:>15,.4f}"
        for t in order
    ]
    msg = "*Hot wallet balances*\n```" + "\n".join(lines) + "```"

    # Append any fetch errors so they're visible in Slack (changed)
    if errors:
        err_lines = "\n".join(f"• {sym}: {err}" for sym, err in errors.items())
        msg += f"\n\n:warning: *Fetch errors:*\n{err_lines}"

    post_to_slack(msg)

if __name__ == "__main__":
    main()
