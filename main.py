import os
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
BIRDEYE_KEY = os.getenv('BIRDEYE_API_KEY')

async def scan_token_birdeye(chain: str, address: str) -> str:
    chain_map = {
        'eth': 'ethereum', 'ethereum': 'ethereum',
        'bsc': 'bsc', 'bnb': 'bsc',
        'base': 'base', 
        'arb': 'arbitrum', 'arbitrum': 'arbitrum',
        'sol': 'solana', 'solana': 'solana',
        'poly': 'polygon', 'polygon': 'polygon'
    }
    
    birdeye_chain = chain_map.get(chain.lower())
    if not birdeye_chain:
        return f"❌ Unsupported chain: `{chain}`. Use: eth, bsc, base, arb, sol"
    
    url = f"https://public-api.birdeye.so/defi/token_overview?address={address}"
    headers = {
        "X-API-KEY": BIRDEYE_KEY, 
        "x-chain": birdeye_chain
    }
    
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as r:
                if r.status == 401:
                    return "❌ Birdeye API key invalid. Check Railway Variables."
                if r.status == 429:
                    return "❌ Rate limited. Wait 60s."
                if r.status != 200:
                    return "❌ Token not found. Check chain/address."
                
                data = (await r.json()).get('data', {})
                if not data:
                    return "❌ Token not found or no data returned."
                
                name = data.get('name', 'Unknown')
                symbol = data.get('symbol', '?')
                mc = data.get('mc', 0) or 0
                liquidity = data.get('liquidity', 0) or 0
                holder = data.get('holder', 0) or 0
                lp_locked = data.get('lpLockedPct', 0) or 0
                price = data.get('price', 0) or 0
                v24h = data.get('v24hUSD', 0) or 0
                
                risk_flags = []
                if liquidity < 10000:
                    risk_flags.append("⚠️ Low LP < $10k")
                if lp_locked < 50:
                    risk_flags.append(f"⚠️ LP only {lp_locked:.1f}% locked")
                if holder < 50:
                    risk_flags.append("⚠️ Holders < 50")
                    
                risk_text = "\n".join(risk_flags) if risk_flags else "✅ No major red flags"
                
                return f"""
🛡️ **Kertia Scan** 

**{name} (${symbol})** | `{birdeye_chain}`
💵 Price: ${price:.8f}
💰 MC: ${mc:,.0f}
📊 24h Vol: ${v24h:,.0f}
💧 LP: ${liquidity:,.0f} | {lp_locked:.1f}% Locked
👥 Holders: {holder:,}

**Risk Check:**
{risk_text}

⚡ Powered by Birdeye
"""
    except Exception as e:
        return f"❌ Scan error: {str(e)[:100]}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚔️ **RAEL_KERTIA v0.7.2 | Trojan Killer**\n\n"
        "Commands:\n/scan <chain> <0x...> - God Mode audit\n\n"
        "Chains: eth, base, bsc, arb, sol"
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "**Usage:** `/scan <chain> <address>`\n"
            "**Example:** `/scan eth 0x4ed4e862860bed51a99a7b96cf246c67a12d5e3d`",
            parse_mode='Markdown'
        )
        return
    
    chain, address = context.args
    msg = await update.message.reply_text("🔍 Scanning...")
    result = await scan_token_birdeye(chain, address)
    await msg.edit_text(result, parse_mode='Markdown')

def main():
    print("Kertia starting...")
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN not set")
        return
    if not BIRDEYE_KEY:
        print("ERROR: BIRDEYE_API_KEY not set")
        return
        
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    
    print("Bot ready - polling Telegram")
    app.run_polling()

if __name__ == "__main__":
    main()
