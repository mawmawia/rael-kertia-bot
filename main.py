import os
import requests
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, InlineQueryHandler, CallbackQueryHandler
import uuid
import asyncio

TOKEN = os.environ['BOT_TOKEN']

CHAINS = {
    "eth": "1", 
    "base": "8453", 
    "bsc": "56",
    "arb": "42161",
    "sol": "solana" # Prepped for Solana
}

# BUGFIX: DexScreener uses different chain names than GoPlus
DEX_CHAIN_MAP = {
    "1": "ethereum",
    "8453": "base",
    "56": "bsc",
    "42161": "arbitrum",
    "solana": "solana"
}

STATUS = {"safe": "🟢", "warn": "🟡", "danger": "🔴", "critical": "🚨"}

def format_price(price):
    if price == 0: return "0.00"
    if price < 0.000001: return f"{price:.10f}"
    if price < 0.01: return f"{price:.6f}"
    if price < 1: return f"{price:.4f}"
    return f"{price:,.2f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "⚔️ **RAEL_KERTIA v0.7 | Trojan Killer**\n\n"
    msg += "**Commands:**\n"
    msg += "/scan <chain> <0x...> - God Mode audit\n"
    msg += "/snipe <chain> <0x...> - Sniper dashboard\n"
    msg += "/price <chain> <0x...> - Live chart data\n\n"
    msg += "**Inline:** `@Rael_kertia_bot 0x...` in any group\n\n"
    msg += "Chains: `eth`, `base`, `bsc`, `arb`, `sol`\n"
    msg += "_We catch soft rugs Trojan misses._"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def get_token_data(chain_id, token):
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={token}"
    try:
        r = requests.get(url, timeout=10).json()
        if r.get("code") == 1 and r.get("result"):
            return r["result"][token.lower()]
    except:
        pass
    return None

async def get_dexscreener_data(dex_chain, token):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"
    try:
        r = requests.get(url, timeout=5).json()
        pairs = r.get('pairs', [])
        for p in pairs:
            if p.get('chainId') == dex_chain:
                return {
                    'price': float(p.get('priceUsd', 0)),
                    'priceChange1h': float(p.get('priceChange', {}).get('h1', 0)),
                    'priceChange24h': float(p.get('priceChange', {}).get('h24', 0)),
                    'volume24h': float(p.get('volume', {}).get('h24', 0)),
                    'liquidity': float(p.get('liquidity', {}).get('usd', 0)),
                    'fdv': float(p.get('fdv', 0)),
                    'dexId': p.get('dexId', 'Unknown'),
                    'url': p.get('url', f'https://dexscreener.com/{dex_chain}/{token}'),
                    'symbol': p.get('baseToken', {}).get('symbol', 'TOKEN')
                }
    except:
        pass
    return None

def calculate_score(data):
    score = 100
    honeypot = data.get("is_honeypot") == "1"
    tax = float(data.get("buy_tax", 0)) + float(data.get("sell_tax", 0))
    owner = data.get("can_take_back_ownership") == "1"
    mint = data.get("is_mintable") == "1"
    cooldown = data.get("is_trading_cooldown") == "1"
    hidden_tax = data.get("hidden_owner") == "1" or data.get("is_anti_whale") == "1"
    transfer_pausable = data.get("transfer_pausable") == "1"
    anti_whale = data.get("is_anti_whale") == "1" # Soft honeypot
    
    # BUGFIX: Sum LP % across all locked addresses, not just first
    lp_holders = data.get("lp_holders", [])
    total_lp_locked = sum([float(h.get("percent", 0)) for h in lp_holders if h.get("
