import os
import asyncio
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import Conflict

TOKEN = os.getenv("TELEGRAM_TOKEN")
BIRDEYE_KEY = os.getenv("BIRDEYE_API_KEY")

print("Kertia starting...")

# Chain mapping for GoPlus + Birdeye
CHAIN_MAP = {
    'eth': '1', 
    'base': '8453', 
    'bsc': '56', 
    'arb': '42161', 
    'op': '10', 
    'poly': '137', 
    'avax': '43114'
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚔️ **RAEL_KERTIA | TROJAN KILLER**\n\n"
        "Deep contract scans + Snipe protection for Base, ETH, BSC.\n\n"
        "**Commands:**\n"
        "`/scan <chain> <address>` - Full token audit\n"
        "`/snipecheck <chain> <address>` - Pre-launch safety check\n\n"
        "**Example:** `/scan base 0x4ed4e862860bed51a99a7b96cf246c67a12d5e3d`\n\n"
        "⚡ Zero fees. Max alpha.",
        parse_mode='Markdown'
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "**Usage:** `/scan <chain> <address>`\n**Example:** `/scan base 0x...`",
            parse_mode='Markdown'
        )
        return
    
    chain, address = context.args
    chain_id = CHAIN_MAP.get(chain.lower())
    if not chain_id:
        await update.message.reply_text(
            f"❌ Unsupported chain: `{chain}`\nUse: eth, base, bsc, arb, op, poly, avax",
            parse_mode='Markdown'
        )
        return
    
    msg = await update.message.reply_text("⚔️ Running GodMode scan...")
    
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # GoPlus Security API
            gp_url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
            # Birdeye Price API  
            be_url = f"https://public-api.birdeye.so/defi/token_overview?address={address}"
            headers = {"X-API-KEY": BIRDEYE_KEY} if BIRDEYE_KEY else {}
            
            gp_task = session.get(gp_url)
            be_task = session.get(be_url, headers=headers)
            
            gp_res, be_res = await asyncio.gather(gp_task, be_task)
            gp_data = (await gp_res.json()).get('result', {}).get(address.lower(), {})
            be_data = (await be_res.json()).get('data', {}) if be_res.status == 200 else {}
            
            if not gp_data:
                await msg.edit_text("❌ Token not found on GoPlus. Check chain + address.")
                return
            
            # Parse GoPlus
            is_hp = gp_data.get('is_honeypot', '0') == '1'
            buy_tax = float(gp_data.get('buy_tax', '0')) * 100
            sell_tax = float(gp_data.get('sell_tax', '0')) * 100
            owner = gp_data.get('owner_address', 'None')
            can_mint = gp_data.get('is_mintable', '0') == '1'
            can_pause = gp_data.get('trading_pausable', '0') == '1'
            owner_renounced = owner in ['', '0x0000000000000000000000000000000000000000', 'None']
            
            # Parse Birdeye
            price = be_data.get('price', 0)
            mcap = be_data.get('mc', 0)
            liquidity = be_data.get('liquidity', 0)
            symbol = gp_data.get('token_symbol', be_data.get('symbol', '?'))
            
            # Score calc
            score = 100
            if is_hp: score -= 50
            if buy_tax > 10: score -= 20
            if sell_tax > 10: score -= 20
            if can_mint: score -= 15
            if can_pause: score -= 15
            if not owner_renounced: score -= 10
            score = max(0, score)
            
            verdict = "🟢 SAFE" if score > 75 else "🟡 RISKY" if score > 40 else "🔴 SCAM"
            
            result = f"""
⚔️ **RAEL_KERTIA AUDIT: ${symbol}**
`{address[:6]}...{address[-4:]}` | {chain.upper()}
——————————————————
**{verdict} | Score: {score}/100**

**Security:**
- **Honeypot:** {'🚨 YES' if is_hp else '✅ No'}
- **Buy Tax:** {buy_tax:.1f}% {'🚨' if buy_tax > 10 else '⚠️' if buy_tax > 5 else '✅'}
- **Sell Tax:** {sell_tax:.1f}% {'🚨' if sell_tax > 10 else '⚠️' if sell_tax > 5 else '✅'}
- **Owner:** {'✅ Renounced' if owner_renounced else f'⚠️ {owner[:10]}...'}
- **Mintable:** {'🚨 Yes' if can_mint else '✅ No'}
- **Pausable:** {'🚨 Yes' if can_pause else '✅ No'}

**Market:**
- **Price:** ${price:.8f}
- **MC:** ${mcap:,.0f}
- **Liquidity:** ${liquidity:,.0f} {'⚠️ Low' if liquidity < 10000 else '✅'}

⚡ **Trojan Killer by Rael_Kertia**
"""
            await msg.edit_text(result, parse_mode='Markdown')
            
    except asyncio.TimeoutError:
        await msg.edit_text("❌ API timeout. Try again in 10s.")
    except Exception as e:
        await msg.edit_text(f"❌ Scan failed: {str(e)[:150]}")

async def snipecheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "**Usage:** `/snipecheck <chain> <address>`\n"
            "**Example:** `/snipecheck base 0x...`\n"
            "Checks if token is safe to snipe before LP add",
            parse_mode='Markdown'
        )
        return
    
    chain, address = context.args
    chain_id = CHAIN_MAP.get(chain.lower())
    if not chain_id:
        await update.message.reply_text(f"❌ Unsupported chain: `{chain}`", parse_mode='Markdown')
        return
        
    msg = await update.message.reply_text("🎯 Running snipe pre-check...")
    
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
            async with session.get(url) as res:
                data = (await res.json()).get('result', {}).get(address.lower(), {})
            
            if not data:
                await msg.edit_text("❌ Token not found. Check chain + address.")
                return
            
            # Snipe-specific flags
            is_honeypot = data.get('is_honeypot', '0') == '1'
            buy_tax = float(data.get('buy_tax', '0')) * 100
            sell_tax = float(data.get('sell_tax', '0')) * 100
            can_mint = data.get('is_mintable', '0') == '1'
            owner_renounced = data.get('owner_address', '') in ['', '0x0000000000000000']
            trading_pausable = data.get('trading_pausable', '0') == '1'
            can_change_fee = data.get('slippage_modifiable', '0') == '1'
            cannot_buy = data.get('cannot_buy', '0') == '1'
            symbol = data.get('token_symbol', '?')
            
            # Verdict logic
            verdict = "✅ SAFE TO SNIPE"
            color = "✅"
            if is_honeypot or buy_tax > 49 or cannot_buy:
                verdict = "🛑 DO NOT SNIPE | Honeypot"
                color = "🚨"
            elif can_mint or trading_pausable:
                verdict = "⚠️ HIGH RISK | Dev has controls"
                color = "⚠️"
            elif sell_tax > 20:
                verdict = "⚠️ RISKY | High sell tax"
                color = "⚠️"
            
            # Slippage calc
            recommended_slip = max(12, int(buy_tax + 5))
            if recommended_slip > 49: recommended_slip = 49
            
            result = f"""
🎯 **SNIPE READINESS: ${symbol}**
`{address[:6]}...{address[-4:]}` | {chain.upper()}
——————————————————
{color} **VERDICT: {verdict}**

**Launch Traps:**
- **Honeypot:** {'🚨 Yes' if is_honeypot else '✅ No'}
- **Cannot Buy:** {'🚨 Yes' if cannot_buy else '✅ No'}
- **Buy Tax:** {buy_tax:.1f}% {'🚨' if buy_tax > 20 else '⚠️' if buy_tax > 5 else '✅'}
- **Sell Tax:** {sell_tax:.1f}% {'🚨' if sell_tax > 20 else '⚠️' if sell_tax > 5 else '✅'}
- **Mintable:** {'🚨 Yes' if can_mint else '✅ No'}
- **Pausable Trading:** {'🚨 Yes' if trading_pausable else '✅ No'}
- **Owner Renounced:** {'✅ Yes' if owner_renounced else '⚠️ No'}
- **Tax Modifiable:** {'⚠️ Yes' if can_change_fee else '✅ No'}
——————————————————
**Recommended Snipe Settings:**
Gas: 0.008 ETH | Slippage: {recommended_slip}%

⚡ **Rael_Kertia Sniper Guard**
"""
            await msg.edit_text(result, parse_mode='Markdown')
            
    except asyncio.TimeoutError:
        await msg.edit_text("❌ API timeout. Try again.")
    except Exception as e:
        await msg.edit_text(f"❌ Snipe check failed: {str(e)[:100]}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    # This catches the Conflict error and prevents crash loops
    if isinstance(context.error, Conflict):
        print("Conflict error caught - another instance was running. Resolved.")
        return
    print(f"Exception while handling update: {context.error}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("snipecheck", snipecheck))
    app.add_error_handler(error_handler)
    
    print("Bot ready - polling Telegram")
    # drop_pending_updates=True is the key fix for Conflict errors
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
