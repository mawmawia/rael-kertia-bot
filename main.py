import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ['BOT_TOKEN']

CHAINS = {
    "eth": "1", 
    "base": "8453", 
    "bsc": "56",
    "arb": "42161"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Rael_kertia online. Trojan Killer active.\n\n"
    msg += "Usage: /scan <chain> <0x...>\n"
    msg += "Chains: eth, base, bsc, arb\n"
    msg += "Ex: /scan base 0x1234...\n\n"
    msg += "Kertia Score beats Trojan."
    await update.message.reply_text(msg)

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /scan <chain> <0x...>\nEx: /scan base 0x1234...")
        return
    
    if len(context.args) == 1:
        chain, token = "eth", context.args[0]
    else:
        chain, token = context.args[0].lower(), context.args[1]
    
    if chain not in CHAINS:
        await update.message.reply_text(f"Chain '{chain}' not supported. Use: eth, base, bsc, arb")
        return
        
    chain_id = CHAINS[chain]
    await update.message.reply_text(f"Scanning {token[:8]}... on {chain.upper()} 🔍")
    
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={token}"
        r = requests.get(url, timeout=10).json()
        
        if r.get("code") != 1 or not r.get("result"):
            await update.message.reply_text("Invalid token or chain not supported yet.")
            return
            
        data = r["result"][token.lower()]
        
        honeypot = data.get("is_honeypot") == "1"
        tax = float(data.get("buy_tax", 0)) + float(data.get("sell_tax", 0))
        owner = data.get("can_take_back_ownership") == "1"
        mint = data.get("is_mintable") == "1"
        lp_status = data.get("lp_holders", [])
        lp_locked = len(lp_status) > 0 and float(lp_status[0].get("percent", 0)) > 95
        
        score = 100
        if honeypot: score -= 50
        if tax > 10: score -= 20
        if owner: score -= 15
        if mint: score -= 10
        if not lp_locked: score -= 15
        score = max(0, score)
        
        verdict = "SAFE" if score > 70 else "CAUTION" if score > 40 else "RUG RISK"
        
        msg = f"Kertia Score: {score}/100\nVerdict: {verdict} {'✅' if score>70 else '⚠️' if score>40 else '🚨'}\n"
        msg += f"Chain: {chain.upper()}\n\n"
        msg += f"Honeypot: {'YES' if honeypot else 'No'}\n"
        msg += f"Total Tax: {tax}%\n"
        msg += f"Owner Risk: {'YES' if owner else 'No'}\n"
        msg += f"Can Mint: {'YES' if mint else 'No'}\n"
        msg += f"LP Locked: {'YES' if lp_locked else 'NO - RUG POSSIBLE'}\n\n"
        msg += "Rael_kertia protects. Trojan misses this."
        
        await update.message.reply_text(msg)
        
    except Exception as e:
        await update.message.reply_text("Scan failed. API timeout or invalid address.")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("scan", scan))
app.run_polling()
