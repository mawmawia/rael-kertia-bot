import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ['BOT_TOKEN']

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Rael_kertia online. Trojan Killer active.\nSend /scan 0xTokenAddress")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /scan 0x1234...")
        return
    
    token = context.args[0]
    await update.message.reply_text(f"Scanning {token}... 🔍")
    
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses={token}"
        r = requests.get(url, timeout=10).json()
        
        if r.get("code")!= 1 or not r.get("result"):
            await update.message.reply_text("Invalid token or chain not supported yet.")
            return
            
        data = r["result"][token.lower()]
        
        honeypot = data.get("is_honeypot") == "1"
        tax = float(data.get("buy_tax", 0)) + float(data.get("sell_tax", 0))
        owner = data.get("can_take_back_ownership") == "1"
        
        score = 100
        if honeypot: score -= 50
        if tax > 10: score -= 30
        if owner: score -= 20
        score = max(0, score)
        
        verdict = "SAFE" if score > 70 else "CAUTION" if score > 40 else "RUG RISK"
        
        msg = f"Kertia Score: {score}/100\nVerdict: {verdict} {'✅' if score>70 else '⚠️' if score>40 else '🚨'}\n\n"
        msg += f"Honeypot: {'YES' if honeypot else 'No'}\n"
        msg += f"Total Tax: {tax}%\n"
        msg += f"Owner Risk: {'YES' if owner else 'No'}\n\n"
        msg += "Rael_kertia protects. Trojan misses this
