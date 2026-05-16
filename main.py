import os
import aiohttp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
BIRDEYE_KEY = os.getenv('BIRDEYE_API_KEY')

async def scan_token_godmode(chain: str, address: str) -> str:
    chain_map = {
        'eth': '1', 'ethereum': '1',
        'bsc': '56', 'bnb': '56', 
        'base': '8453',
        'arb': '42161', 'arbitrum': '42161',
        'sol': 'solana', 'solana': 'solana',
        'poly': '137', 'polygon': '137'
    }
    chain_map_birdeye = {
        'eth': 'ethereum', 'ethereum': 'ethereum',
        'bsc': 'bsc', 'bnb': 'bsc', 
        'base': 'base',
        'arb': 'arbitrum', 'arbitrum': 'arbitrum',
        'sol': 'solana', 'solana': 'solana',
        'poly': 'polygon', 'polygon': 'polygon'
    }
    
    chain_id = chain_map.get(chain.lower())
    birdeye_chain = chain_map_birdeye.get(chain.lower())
    
    if not chain_id or not birdeye_chain:
        return f"❌ Unsupported chain: `{chain}`. Use: eth, bsc, base, arb, sol"
    
    timeout = aiohttp.ClientTimeout(total=8)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Birdeye for price/MC/LP
            birdeye_url = f"https://public-api.birdeye.so/defi/token_overview?address={address}"
            birdeye_headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": birdeye_chain}
            
            # GoPlus for security
            goplus_url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
            
            birdeye_task = session.get(birdeye_url, headers=birdeye_headers)
            goplus_task = session.get(goplus_url)
            
            birdeye_res, goplus_res = await asyncio.gather(birdeye_task, goplus_task)
            
            # Parse Birdeye
            bd_data = {}
            if birdeye_res.status == 200:
                bd_data = (await birdeye_res.json()).get('data', {})
            
            # Parse GoPlus
            gp_data = {}
            if goplus_res.status == 200:
                gp_json = await goplus_res.json()
                gp_data = gp_json.get('result', {}).get(address.lower(), {})
            
            if not bd_data and not gp_data:
                return "❌ Token not found on Birdeye or GoPlus. Check chain/address."
            
            # Combine data
            name = bd_data.get('name') or gp_data.get('token_name', 'Unknown')
            symbol = bd_data.get('symbol') or gp_data.get('token_symbol', '?')
            price = bd_data.get('price', 0) or 0
            mc = bd_data.get('mc', 0) or 0
            liquidity = bd_data.get('liquidity', 0) or 0
            holder = bd_data.get('holder', 0) or int(gp_data.get('holder_count', 0))
            v24h = bd_data.get('v24hUSD', 0) or 0
            lp_locked = bd_data.get('lpLockedPct', 0) or 0
            v1h = bd_data.get('v1hChangePercent', 0) or 0
            v24h_pct = bd_data.get('v24hChangePercent', 0) or 0
            
            # GoPlus security flags
            is_honeypot = gp_data.get('is_honeypot', '0') == '1'
            buy_tax = float(gp_data.get('buy_tax', '0')) * 100
            sell_tax = float(gp_data.get('sell_tax', '0')) * 100
            owner_address = gp_data.get('owner_address', '')
            owner_renounced = owner_address in ['', '0x0000000000000000', '0x000000000000000000000000000000000000dead']
            is_mintable = gp_data.get('is_mintable', '0') == '1'
            can_take_ownership = gp_data.get('can_take_back_ownership', '0') == '1'
            is_anti_whale = gp_data.get('is_anti_whale', '0') == '1'
            trading_cooldown = gp_data.get('trading_cooldown', '0') == '1'
            
            # Calculate Score
            score = 100
            threats = 0
            if is_honeypot: score -= 50; threats += 1
            if buy_tax > 10 or sell_tax > 10: score -= 20; threats += 1
            if lp_locked < 50: score -= 15; threats += 1
            if liquidity < 10000: score -= 10
            if is_mintable: score -= 15; threats += 1
            if can_take_ownership: score -= 10
            if not owner_renounced: score -= 10
            score = max(0, score)
            
            risk_level = "SAFE" if score >= 70 else "MEDIUM RISK" if score >= 40 else "RUG RISK"
            risk_emoji = "✅" if score >= 70 else "⚠️" if score >= 40 else "🚨"
            
            # Hidden tax logic
            hidden_tax_text = "🚨 DETECTED" if buy_tax > 5 or sell_tax > 5 else "✅ None"
            trojan_warning = "\n⚠️ **Trojan didn't see this!** Hidden Tax detected." if buy_tax > 5 or sell_tax > 5 else ""
            soft_hp_warning = "\n⚠️ **Soft Honeypot:** Anti-whale limits selling." if is_anti_whale else ""
            
            return f"""
⚔️ **RAEL_KERTIA AUDIT: ${symbol}**
`{address[:6]}...{address[-4:]}` | {chain.upper()}

🛡️ **Score: {score}/100 | {risk_level}** {risk_emoji}
——————————————————
- **Honeypot:** {'🚨 Yes' if is_honeypot else '✅ No'}
- **Taxes:** Buy {buy_tax:.1f}% / Sell {sell_tax:.1f}% {'✅' if buy_tax < 5 and sell_tax < 5 else '⚠️'}
- **LP Locked:** {lp_locked:.1f}% {'✅' if lp_locked >= 50 else '❌ UNLOCKED'}
- **Ownership:** {'✅ Renounced' if owner_renounced else '⚠️ Not Renounced'}
- **Hidden Tax:** {hidden_tax_text}
- **Anti-Whale:** {'⚠️ Enabled' if is_anti_whale else '✅ None'}
- **Mintable:** {'🚨 Yes' if is_mintable else '✅ No'}
- **Cooldown:** {'⚠️ Yes' if trading_cooldown else '✅ None'}
- **Whale Risk:** {'⚠️ High' if can_take_ownership else '✅ Low'}
——————————————————
💰 **Live Alpha:**
- **Price:** ${price:.8f}
- **1h:** {v1h:+.1f}% | **24h:** {v24h_pct:+.1f}%
- **Liquidity:** ${liquidity:,.0f} | **Holders:** {holder:,}
{trojan_warning}{soft_hp_warning}

⚡ **Scanned by Rael_Kertia | Threats Neutralized: {threats}**
"""
            
    except asyncio.TimeoutError:
        return "❌ API timeout. Try again."
    except Exception as e:
        return f"❌ Scan error: {str(e)[:100]}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚔️ **RAEL_KERTIA v0.7.2 | Trojan Killer**\n\n"
        "Commands:\n"
        "/scan <chain> <0x...> - God Mode audit\n\n"
        "Chains: eth, base, bsc, arb, sol\n"
        "We catch soft rugs Trojan misses.",
        parse_mode='Markdown'
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "**Usage:** `/scan <chain> <address>`\n"
            "**Example:** `/scan eth 0x4ed4e862860bed51a99a7b96cf246c67a12d5e3d`\n"
            "**Chains:** eth, bsc, base, arb, sol",
            parse_mode='Markdown'
        )
        return
    
    chain, address = context.args
    msg = await update.message.reply_text("🔍 Scanning...")
    
    result = await scan_token_godmode(chain, address)
    
    # Add buttons
    keyboard = [
        [InlineKeyboardButton("📊 Chart", url=f"https://dexscreener.com/{chain}/{address}"),
         InlineKeyboardButton("🛡️ GoPlus", url=f"https://gopluslabs.io/token-security/{chain_map.get(chain.lower(), '1')}/{address}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(result, parse_mode='Markdown', reply_markup=reply_markup, disable_web_page_preview=True)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Kertia online ⚡")

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
    app.add_handler(CommandHandler("ping", ping))
    
    print("Bot ready - polling Telegram")
    app.run_polling()

if __name__ == "__main__":
    # Fix chain_map scope issue for buttons
    chain_map = {
        'eth': '1', 'ethereum': '1', 'bsc': '56', 'bnb': '56', 
        'base': '8453', 'arb': '42161', 'arbitrum': '42161',
        'poly': '137', 'polygon': '137'
    }
    main()
