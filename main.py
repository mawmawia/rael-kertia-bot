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
    msg += "/scan <chain> <0
