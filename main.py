print("RAEL_KERTIA: Boot sequence initiated")
import os
print("RAEL_KERTIA: os imported")

TOKEN = os.environ['BOT_TOKEN']
print(f"RAEL_KERTIA: Token loaded: {TOKEN[:10]}...")

import requests
print("RAEL_KERTIA: requests imported")

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
print("RAEL_KERTIA: telegram imports OK")

from telegram.ext import Application, CommandHandler, ContextTypes, InlineQueryHandler, CallbackQueryHandler
print("RAEL_KERTIA: telegram.ext imports OK")

import uuid
import asyncio
print("RAEL_KERTIA: All imports complete")

# Social Proof Counter
total_scans = 0

CHAINS = {
    "eth": "1", 
    "base": "8453", 
    "bsc": "56",
    "arb": "42161",
    "sol": "solana"
}

DEX_CHAIN_MAP = {
    "1": "ethereum",
    "8453": "base",
    "56": "bsc",
    "42161": "arbitrum",
    "solana": "solana"
}

def safe_float(val, default=0.0):
    """Crash-proof float conversion for API data"""
    try:
        if val is None or val == "" or val == "None":
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

def format_price(price):
    if price == 0: return "0.00"
    if price < 0.000001: return f"{price:.10f}"
    if price < 0.01: return f"{price:.6f}"
    if price < 1: return f"{price:.4f}"
    return f"{price:,.2f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "⚔️ **RAEL_KERTIA v0.7.2 | Trojan Killer**\n\n"
    msg += "**Commands:**\n"
    msg += "/scan <chain> <0x...> - God Mode audit\n"
    msg += "/snipe <chain> <0x...> - Sniper dashboard\n"
    msg += "/price <chain> <0x...> - Live chart data\n\n"
    msg += "**Inline:** `@Rael_kertia_bot 0x...` in any group\n\n"
    msg += "Chains: `eth`, `base`, `bsc`, `arb`, `sol`\n"
    msg += f"_Threats Neutralized: `{total_scans}`_\n"
    msg += "_We catch soft rugs Trojan misses._"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def get_token_data(chain_id, token):
    # FIX 1: Solana addresses are case-sensitive Base58
    addr = token if chain_id == "solana" else token.lower()
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={addr}"
    try:
        r = requests.get(url, timeout=10).json()
        if r.get("code") == 1 and r.get("result"):
            return r["result"][addr] # Use same casing as request
    except Exception as e:
        print(f"GoPlus API Error: {e}")
    return None

async def get_dexscreener_data(dex_chain, token):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"
    try:
        r = requests.get(url, timeout=5).json()
        pairs = r.get('pairs', [])
        # FIX 2: Pick highest liquidity pair on chain
        best_pair = None
        best_liq = 0
        for p in pairs:
            if p.get('chainId') == dex_chain:
                liq = safe_float(p.get('liquidity', {}).get('usd', 0))
                if liq > best_liq:
                    best_liq = liq
                    best_pair = p
        
        if best_pair:
            return {
                'price': safe_float(best_pair.get('priceUsd', 0)),
                'priceChange1h': safe_float(best_pair.get('priceChange', {}).get('h1', 0)),
                'priceChange24h': safe_float(best_pair.get('priceChange', {}).get('h24', 0)),
                'volume24h': safe_float(best_pair.get('volume', {}).get('h24', 0)),
                'liquidity': safe_float(best_pair.get('liquidity', {}).get('usd', 0)),
                'fdv': safe_float(best_pair.get('fdv', 0)),
                'dexId': best_pair.get('dexId
