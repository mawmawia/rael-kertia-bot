import asyncio
import aiohttp
import sys
import os
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.helpers import escape

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
BIRDEYE_KEY = os.getenv("BIRDEYE_API_KEY")

CHAIN_MAP = {
    'eth': '1', 'base': '8453', 'bsc': '56',
    'arb': '42161', 'op': '10', 'poly': '137', 'avax': '43114'
}

BIRDEYE_CHAIN = {
    'eth': 'ethereum', 'base': 'base', 'bsc': 'bsc',
    'arb': 'arbitrum', 'op': 'optimism', 'poly': 'polygon', 'avax': 'avalanche'
}

DEX_CHAIN = {
    'eth': 'ethereum', 'base': 'base', 'bsc': 'bsc',
    'arb': 'arbitrum', 'op': 'optimism', 'poly': 'polygon'
}

# --- SESSION MANAGEMENT & APPLICATION STARTUP ---
async def init_session(app: Application):
    # Fix 1: Clear dangling webhook parameters securely within the loop thread initialization
    print("Clearing prior webhook registrations...")
    await app.bot.delete_webhook(drop_pending_updates=True)
    
    timeout = aiohttp.ClientTimeout(total=15)
    app.bot_data['session'] = aiohttp.ClientSession(timeout=timeout)
    print("Kertia starting... Engine online.")

async def close_session(app: Application):
    session = app.bot_data.get('session')
    if session:
        await session.close()
    print("Session closed cleanly.")

# --- ERROR HANDLER: Trojan Killer Graceful Shutdown ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if "Conflict" in str(err) or "terminated by other getUpdates" in str(err):
        print("Conflict state identified! Forcing instance shutdown to allow clean Railway takeover...")
        sys.exit(1)
    print(f"An error occurred: {err}")

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "⚔️ <b>RAEL_KERTIA | TROJAN KILLER</b>\n\n"
        "Deep contract scans + Snipe protection for Base, ETH, BSC.\n\n"
        "<b>Commands:</b>\n"
        "/scan &lt;chain&gt; &lt;address&gt; - Full token audit\n"
        "/snipecheck &lt;chain&gt; &lt;address&gt; - Pre-launch safety check\n"
        "/trade - Open Rael Terminal\n\n"
        "<b>Example:</b> <code>/scan base 0x4ed4e862860bed51a99a7b96cf246c67a12d5e3d</code>\n\n"
        "⚡ Zero fees. Max alpha."
    )

async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(
        "⚔️ Open Rael Terminal",
        web_app=WebAppInfo(url="https://rael-kertia.vercel.app")
    )]]
    await update.message.reply_text(
        "Launch the Rael_Kertia Terminal:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_html(
            "<b>Usage:</b> <code>/scan &lt;chain&gt; &lt;address&gt;</code>\n"
            "<b>Example:</b> <code>/scan eth 0x...</code>"
        )
        return

    chain, address = context.args
    address = address.lower().strip()
    chain_id = CHAIN_MAP.get(chain.lower())
    if not chain_id:
        await update.message.reply_html(f"❌ Unsupported chain: <code>{escape(chain)}</code>")
        return

    msg = await update.message.reply_text("⚔️ Running GodMode scan...")
    session = context.application.bot_data['session']

    be_chain = BIRDEYE_CHAIN.get(chain.lower(), 'ethereum')
    dex_chain = DEX_CHAIN.get(chain.lower(), 'ethereum')

    try:
        gp_url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        be_url = f"https://public-api.birdeye.so/defi/token_overview?address={address}&chain={be_chain}"
        dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"

        headers = {"X-API-KEY": BIRDEYE_KEY} if BIRDEYE_KEY else {}

        gp_task = session.get(gp_url)
        be_task = session.get(be_url, headers=headers)
        dex_task = session.get(dex_url)
        gp_res, be_res, dex_res = await asyncio.gather(gp_task, be_task, dex_task, return_exceptions=True)

        # Handle structural query responses safely
        gp_data = {}
        if not isinstance(gp_res, Exception) and gp_res.status == 200:
            gp_json = await gp_res.json()
            # Fix 2: Normalize GoPlus dictionary keys to lowercase to bypass checksum mismatch issues
            raw_results = gp_json.get('result', {}) or {}
            normalized_results = {str(k).lower(): v for k, v in raw_results.items()}
            gp_data = normalized_results.get(address, {})

        be_data = {}
        if not isinstance(be_res, Exception) and be_res.status == 200:
            be_json = await be_res.json()
            be_data = be_json.get('data', {}) or {}

        dex_data = {}
        if not isinstance(dex_res, Exception) and dex_res.status == 200:
            dex_json = await dex_res.json()
            pairs = dex_json.get('pairs', [])
            if pairs:
                dex_data = next((p for p in pairs if str(p.get('chainId')).lower() == dex_chain), pairs[0])

        if not gp_data and not be_data and not dex_data:
            await msg.edit_text("❌ Token not found across tracking endpoints. Verify chain alignment.")
            return

        # --- Parse Security Data ---
        def parse_tax(val):
            v = float(val or 0)
            return v * 100 if 0 < v < 1.0 else v

        is_hp = gp_data.get('is_honeypot', '0') == '1'
        buy_tax = parse_tax(gp_data.get('buy_tax', '0'))
        sell_tax = parse_tax(gp_data.get('sell_tax', '0'))
        owner = gp_data.get('owner_address', 'None')
        can_mint = gp_data.get('is_mintable', '0') == '1'
        can_pause = gp_data.get('trading_pausable', '0') == '1'
        owner_renounced = owner.lower() in ['', '0x0000000000000000', 'none', '0x000000000000000000000000dead', '0x0000000000000000000000000000000000000000']

        hidden_tax = gp_data.get('hidden_owner', '0') == '1' or gp_data.get('cannot_buy', '0') == '1'
        anti_whale = gp_data.get('is_anti_whale', '0') == '1' or float(gp_data.get('max_tx_amount', '0') or 0) > 0
        cooldown = gp_data.get('trade_cooldown', '0') == '1' or int(gp_data.get('trade_cooldown', '0') or 0) > 0
        
        # Fix 3: Safer LP calculation engine
        lp_holders = gp_data.get('lp_holders', [])
        lp_total = float(gp_data.get('lp_total_supply', '0') or 0)
        lp_locked_pct = 0.0
        if lp_holders and lp_total > 0:
            locked_amt = 0.0
            for h in lp_holders:
                addr = str(h.get('address', '')).lower()
                tag = str(h.get('tag', '')).lower()
                is_dead_wallet = any(x in addr for x in ['dead', 'null', '0000000000000000000000000000000000000000'])
                is_lock_contract = 'lock' in tag or h.get('is_locked') == 1
                
                if is_dead_wallet or is_lock_contract:
                    # Treat calculation ratio as percentage balance out of box safely
                    locked_amt += float(h.get('percent', 0) or 0) * lp_total
            
            lp_locked_pct = (locked_amt / lp_total) * 100 if lp_total else 0.0
            # Guard upper bounds if API combines data representations
            if lp_locked_pct > 100.0 or gp_data.get('lp_total_supply') is None:
                lp_locked_pct = sum(float(h.get('percent', 0) or 0) for h in lp_holders if any(x in str(h.get('address','')).lower() for x in ['dead', 'null', '0000']) or 'lock' in str(h.get('tag','')).lower()) * 100

        # --- Parse Market Data ---
        price = float(be_data.get('price') or dex_data.get('priceUsd') or 0)
        mcap = float(be_data.get('mc') or dex_data.get('fdv') or 0)
        liquidity = float(be_data.get('liquidity') or dex_data.get('liquidity', {}).get('usd') or 0)
        symbol = escape(gp_data.get('token_symbol') or be_data.get('symbol') or dex_data.get('baseToken', {}).get('symbol', 'UNKNOWN'))

        price_change = dex_data.get('priceChange', {})
        h1 = float(price_change.get('h1') or 0)
        h24 = float(price_change.get('h24') or 0)
        holders = int(gp_data.get('holder_count') or dex_data.get('info', {}).get('holders') or 0)
        pair_addr = dex_data.get('pairAddress', '')

        # --- Scoring Engine ---
        score = 100
        threats = 0
        if is_hp: score -= 50; threats += 1
        if buy_tax > 10 or sell_tax > 10: score -= 25; threats += 1
        if hidden_tax: score -= 30; threats += 1
        if can_mint: score -= 15; threats += 1
        if can_pause: score -= 15; threats += 1
        if not owner_renounced: score -= 10; threats += 1
        if lp_locked_pct < 50: score -= 20; threats += 1
        if anti_whale: score -= 10
        score = max(0, score)

        if score > 75: verdict = "🟢 SAFE"
        elif score > 40: verdict = "🟡 RISKY"
        else: verdict = "🔴 RUG RISK"

        owner_display = "Renounced" if owner_renounced else f"{owner[:6]}...{owner[-4:]}"
        lp_status = f"{lp_locked_pct:.1f}% {'✅' if lp_locked_pct > 80 else '⚠️' if lp_locked_pct > 50 else '❌ UNLOCKED'}"
        tax_display = f"Buy/Sell {buy_tax:.1f}%/{sell_tax:.1f}% {'✅' if buy_tax < 5 and sell_tax < 5 else '⚠️' if buy_tax < 10 else '🚨'}"

        result = f"""⚔️ <b>RAEL_KERTIA AUDIT: ${symbol}</b>
<code>{address[:6]}...{address[-4:]}</code> | {chain.upper()}

🛡️ <b>Score: {score}/100 | {verdict.replace('🟢 ','').replace('🟡 ','').replace('🔴 ','')}</b>
——————————————————

- <b>Honeypot:</b> {'🚨 YES' if is_hp else '✅ No'}
- <b>Taxes:</b> {tax_display}
- <b>LP Locked:</b> {lp_status}
- <b>Ownership:</b> {'✅ ' if owner_renounced else '⚠️ '}{owner_display}
- <b>Hidden Tax:</b> {'🚨 DETECTED' if hidden_tax else '✅ No'}
- <b>Anti-Whale:</b> {'⚠️ Enabled' if anti_whale else '✅ No'}
- <b>Mintable:</b> {'🚨 Yes' if can_mint else '✅ No'}
- <b>Cooldown:</b> {'⚠️ Enabled' if cooldown else '✅ None'}
- <b>Whale Risk:</b> {'⚠️ High' if anti_whale else '✅ Low'}
——————————————————

💰 <b>Live Alpha:</b>
- <b>Price:</b> ${price:.8f}
- <b>1h:</b> {'📉' if h1 < 0 else '📈'} {h1:.1f}% | <b>24h:</b> {h24:.1f}%
- <b>Liquidity:</b> ${liquidity:,.0f} | <b>Holders:</b> {holders}
"""

        if hidden_tax:
            result += "\n⚠️ <b>Trojan didn't see this! Hidden Tax detected.</b>"
        if anti_whale and not is_hp:
            result += "\n⚠️ <b>Soft Honeypot: Anti-whale limits selling.</b>"
        if 0 < lp_locked_pct < 50:
            result += "\n⚠️ <b>Rug Risk: LP not locked safely.</b>"
        if lp_locked_pct == 0 and liquidity > 1000:
            result += "\n⚠️ <b>Rug Risk: LP completely unlocked.</b>"

        result += f"\n\n🛡️ <i>Scanned by Rael_Kertia | Threats Neutralized: {threats}</i>"

        kb = []
        if pair_addr:
            kb.append([InlineKeyboardButton("📊 Chart", url=f"https://dexscreener.com/{dex_chain}/{pair_addr}")])
        kb.append([InlineKeyboardButton("🛡️ GoPlus Report", url=f"https://gopluslabs.io/token-security/{chain_id}/{address}")])

        await msg.edit_text(result, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)

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
        gp_url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        async with session.get(gp_url) as res:
            data = await res.json()

        if data.get('code') != 1 or not data.get('result'):
            await msg.edit_text("❌ Token metadata verification empty. Check configuration details.")
            return

        raw_results = data.get('result', {}) or {}
        normalized_results = {str(k).lower(): v for k, v in raw_results.items()}
        gp_data = normalized_results.get(address, {})
        
        if not gp_data:
            await msg.edit_text("❌ Token parsing data failed. Address could be unindexed.")
            return

        is_hp = gp_data.get('is_honeypot', '0') == '1'
        owner = gp_data.get('owner_address', 'None')
        owner_renounced = owner.lower() in ['', '0x0000000000000000', 'none', '0x000000000000000000000000000000000000dead']
        hidden_tax = gp_data.get('hidden_owner', '0') == '1' or gp_data.get('cannot_buy', '0') == '1'

        if is_hp: verdict = "🔴 FATAL: Honeypot Detected"
        elif hidden_tax: verdict = "🔴 FATAL: Hidden Tax / Purchase Block"
        elif not owner_renounced: verdict = "🟡 HIGH RISK: Owner Not Renounced"
        else: verdict = "🟢 CLEAR: No blocking risks detected"

        result = f"""⚔️ <b>RAEL_KERTIA SNIPECHECK</b>
<code>{address[:6]}...{address[-4:]}</code> | {chain.upper()}
——————————————————
<b>Verdict: {verdict}</b>

- <b>Honeypot:</b> {'🚨 YES' if is_hp else '✅ No'}
- <b>Ownership:</b> {'✅ Renounced' if owner_renounced else '⚠️ Not Renounced'}
- <b>Hidden Tax:</b> {'🚨 Detected' if hidden_tax else '✅ No'}
- <b>Mintable:</b> {'🚨 Yes' if gp_data.get('is_mintable', '0') == '1' else '✅ No'}

⚡ <i>Snipe at your own risk. Trojan Killer engaged.</i>"""

        await msg.edit_text(result, parse_mode='HTML')

    except Exception as e:
        await msg.edit_text(f"❌ Snipecheck failed: {escape(str(e)[:120])}")

# --- MAIN ENGINE ENTRY ---
def main():
    app = Application.builder().token(TOKEN).build()

    app.post_init = init_session
    app.post_shutdown = close_session

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("snipecheck", snipecheck))
    app.add_handler(CommandHandler("trade", trade))
    app.add_error_handler(error_handler)

    print("Bot ready - polling Telegram")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
