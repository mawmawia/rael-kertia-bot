import os
import sys
import asyncio
import aiohttp
from html import escape
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

async def init_session(app: Application):
    timeout = aiohttp.ClientTimeout(total=12)
    app.bot_data['session'] = aiohttp.ClientSession(timeout=timeout)

async def close_session(app: Application):
    session = app.bot_data.get('session')
    if session:
        await session.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "⚔️ <b>RAEL_KERTIA | TROJAN KILLER</b>\n\n"
        "Deep contract scans + Snipe protection for Base, ETH, BSC.\n\n"
        "<b>Commands:</b>\n"
        "<code>/scan &lt;chain&gt; &lt;address&gt;</code> - Full token audit\n"
        "<code>/snipecheck &lt;chain&gt; &lt;address&gt;</code> - Pre-launch safety check\n\n"
        "<b>Example:</b> <code>/scan base 0x4ed4e862860bed51a99a7b96cf246c67a12d5e3d</code>\n\n"
        "⚡ Zero fees. Max alpha."
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_html(
            "<b>Usage:</b> <code>/scan &lt;chain&gt; &lt;address&gt;</code>\n"
            "<b>Example:</b> <code>/scan base 0x...</code>"
        )
        return
    
    chain, address = context.args
    address = address.lower().strip()
    chain_id = CHAIN_MAP.get(chain.lower())
    if not chain_id:
        await update.message.reply_html(
            f"❌ Unsupported chain: <code>{escape(chain)}</code>\n"
            "Use: eth, base, bsc, arb, op, poly, avax"
        )
        return
    
    msg = await update.message.reply_text("⚔️ Running GodMode scan...")
    session = context.application.bot_data['session']
    
    try:
        gp_url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        be_url = f"https://public-api.birdeye.so/defi/token_overview?address={address}"
        headers = {"X-API-KEY": BIRDEYE_KEY} if BIRDEYE_KEY else {}
        
        gp_task = session.get(gp_url)
        be_task = session.get(be_url, headers=headers)
        gp_res, be_res = await asyncio.gather(gp_task, be_task)
        
        gp_json = await gp_res.json()
        gp_data = gp_json.get('result', {}).get(address, {}) if gp_json.get('code') == 1 else {}
        
        be_data = {}
        if be_res.status == 200:
            be_json = await be_res.json()
            be_data = be_json.get('data', {}) or {}
        
        if not gp_data and not be_data:
            await msg.edit_text("❌ Token data lookup failed. Verify address and selected chain alignment.")
            return
        
        def parse_tax(val):
            v = float(val or 0)
            return v * 100 if 0 < v < 1.0 else v

        is_hp = gp_data.get('is_honeypot', '0') == '1'
        buy_tax = parse_tax(gp_data.get('buy_tax', '0'))
        sell_tax = parse_tax(gp_data.get('sell_tax', '0'))
        owner = gp_data.get('owner_address', 'None')
        can_mint = gp_data.get('is_mintable', '0') == '1'
        can_pause = gp_data.get('trading_pausable', '0') == '1'
        owner_renounced = owner.lower() in ['', '0x0000000000000000000000000000000000000000', 'none']
        
        price = be_data.get('price', 0) or 0
        mcap = be_data.get('mc', 0) or 0
        liquidity = be_data.get('liquidity', 0) or 0
        symbol = escape(gp_data.get('token_symbol', be_data.get('symbol', 'UNKNOWN')))
        
        score = 100
        if is_hp: score -= 50
        if buy_tax > 10: score -= 20
        if sell_tax > 10: score -= 20
        if can_mint: score -= 15
        if can_pause: score -= 15
        if not owner_renounced: score -= 10
        score = max(0, score)
        
        verdict = "🟢 SAFE" if score > 75 else "🟡 RISKY" if score > 40 else "🔴 SCAM"
        owner_display = "Renounced" if owner_renounced else f"{owner[:6]}...{owner[-4:]}"
        
        result = f"""⚔️ <b>RAEL_KERTIA AUDIT: ${symbol}</b>
<code>{address[:6]}...{address[-4:]}</code> | {chain.upper()}
——————————————————
<b>{verdict} | Score: {score}/100</b>

<b>Security:</b>
- <b>Honeypot:</b> {'🚨 YES' if is_hp else '✅ No'}
- <b>Buy Tax:</b> {buy_tax:.1f}% {'🚨' if buy_tax > 10 else '⚠️' if buy_tax > 5 else '✅'}
- <b>Sell Tax:</b> {sell_tax:.1f}% {'🚨' if sell_tax > 10 else '⚠️' if sell_tax > 5 else '✅'}
- <b>Owner:</b> {'✅ ' if owner_renounced else '⚠️ '}{owner_display}
- <b>Mintable:</b> {'🚨 Yes' if can_mint else '✅ No'}
- <b>Pausable:</b> {'🚨 Yes' if can_pause else '✅ No'}

<b>Market:</b>
- <b>Price:</b> ${price:.8f}
- <b>MC:</b> ${mcap:,.0f}
- <b>Liquidity:</b> ${liquidity:,.0f} {'⚠️ Low' if liquidity < 10000 else '✅'}

⚡ <b>Trojan Killer by Rael_Kertia</b>"""

        await msg.edit_text(result, parse_mode='HTML')
            
    except asyncio.TimeoutError:
        await msg.edit_text("❌ API connection timed out. Try again.")
    except Exception as e:
        await msg.edit_text(f"❌ Scan execution failed: {escape(str(e)[:120])}")

async def snipecheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_html(
            "<b>Usage:</b> <code>/snipecheck &lt;chain&gt; &lt;address&gt;</code>\n"
            "<b>Example:</b> <code>/snipecheck base 0x...</code>"
        )
        return
    
    chain, address = context.args
    address = address.lower().strip()
    chain_id = CHAIN_MAP.get(chain.lower())
    if not chain_id:
        await update.message.reply_html(f"❌ Unsupported chain: <code>{escape(chain)}</code>")
        return
        
    msg = await update.message.reply_text("🎯 Running snipe pre-check...")
    session = context.application.bot_data['session']
    
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        async with session.get(url) as res:
            res_json = await res.json()
            data = res_json.get('result', {}).get(address, {}) if res_json.get('code') == 1 else {}
            
        if not data:
            await msg.edit_text("❌ Token metadata verification empty. Check configuration details.")
            return
            
        def parse_tax(val):
            v = float(val or 0)
            return v * 100 if 0 < v < 1.0 else v

        is_honeypot = data.get('is_honeypot', '0') == '1'
        buy_tax = parse_tax(data.get('buy_tax', '0'))
        sell_tax = parse_tax(data.get('sell_tax', '0'))
        can_mint = data.get('is_mintable', '0') == '1'
        owner = data.get('owner_address', '')
        owner_renounced = owner.lower() in ['', '0x0000000000000000000000000000000000000000']
        trading_pausable = data.get('trading_pausable', '0') == '1'
        can_change_fee = data.get('slippage_modifiable', '0') == '1'
        cannot_buy = data.get('cannot_buy', '0') == '1'
        symbol = escape(data.get('token_symbol', 'UNKNOWN'))
        
        verdict = "✅ SAFE TO SNIPE"
        color = "✅"
        if is_honeypot or buy_tax > 49 or cannot_buy:
            verdict = "🛑 DO NOT SNIPE | Honeypot"
            color = "🚨"
        elif can_mint or trading_pausable:
            verdict = "⚠️ HIGH RISK | Dev controls active"
            color = "⚠️"
        elif sell_tax > 20:
            verdict = "⚠️ RISKY | Elevated sell tax structures"
            color = "⚠️"
        
        recommended_slip = max(12, int(buy_tax + 5))
        if recommended_slip > 49: recommended_slip = 49
        
        result = f"""🎯 <b>SNIPE READINESS: ${symbol}</b>
<code>{address[:6]}...{address[-4:]}</code> | {chain.upper()}
——————————————————
{color} <b>VERDICT: {verdict}</b>

<b>Launch Traps:</b>
- <b>Honeypot:</b> {'🚨 Yes' if is_honeypot else '✅ No'}
- <b>Cannot Buy:</b> {'🚨 Yes' if cannot_buy else '✅ No'}
- <b>Buy Tax:</b> {buy_tax:.1f}% {'🚨' if buy_tax > 20 else '⚠️' if buy_tax > 5 else '✅'}
- <b>Sell Tax:</b> {sell_tax:.1f}% {'🚨' if sell_tax > 20 else '⚠️' if sell_tax > 5 else '✅'}
- <b>Mintable:</b> {'🚨 Yes' if can_mint else '✅ No'}
- <b>Pausable Trading:</b> {'🚨 Yes' if trading_pausable else '✅ No'}
- <b>Owner Renounced:</b> {'✅ Yes' if owner_renounced else '⚠️ No'}
- <b>Tax Modifiable:</b> {'⚠️ Yes' if can_change_fee else '✅ No'}
——————————————————
<b>Recommended Snipe Settings:</b>
Gas: <code>0.008 ETH</code> | Slippage: <code>{recommended_slip}%</code>

⚡ <b>Rael_Kertia Sniper Guard</b>"""

        await msg.edit_text(result, parse_mode='HTML')
            
    except asyncio.TimeoutError:
        await msg.edit_text("❌ Connection timed out during live safety audit.")
    except Exception as e:
        await msg.edit_text(f"❌ Snipe check execution failed: {escape(str(e)[:100])}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, Conflict):
        print("Conflict state identified! Forcing instance termination to allow fresh container take-over...")
        sys.exit(1)
    print(f"Exception while handling update: {context.error}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.post_init = init_session
    app.post_shutdown = close_session
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("snipecheck", snipecheck))
    app.add_error_handler(error_handler)
    
    print("Bot ready - polling Telegram")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
