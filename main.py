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
    msg = "⚔️ <b>RAEL_KERTIA v0.7.2 | Trojan Killer</b>\n\n"
    msg += "<b>Commands:</b>\n"
    msg += "/scan &lt;chain&gt; &lt;0x...&gt; - God Mode audit\n"
    msg += "/snipe &lt;chain&gt; &lt;0x...&gt; - Sniper dashboard\n"
    msg += "/price &lt;chain&gt; &lt;0x...&gt; - Live chart data\n\n"
    msg += "<b>Inline:</b> @Rael_kertia_bot 0x... in any group\n\n"
    msg += "Chains: <code>eth</code>, <code>base</code>, <code>bsc</code>, <code>arb</code>, <code>sol</code>\n"
    msg += f"<i>Threats Neutralized: <code>{total_scans}</code></i>\n"
    msg += "<i>We catch soft rugs Trojan misses.</i>"
    await update.message.reply_text(msg, parse_mode='HTML')

async def get_token_data(chain_id, token):
    addr = token if chain_id == "solana" else token.lower()
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={addr}"
    try:
        r = requests.get(url, timeout=10).json()
        if r.get("code") == 1 and r.get("result"):
            return r["result"].get(addr, {})
    except Exception as e:
        print(f"GoPlus API Error: {e}")
    return None

async def get_dexscreener_data(dex_chain, token):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"
    try:
        r = requests.get(url, timeout=5).json()
        pairs = r.get('pairs', [])
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
                'dexId': best_pair.get('dexId', 'Unknown'),
                'url': best_pair.get('url', f'https://dexscreener.com/{dex_chain}/{token}'),
                'symbol': best_pair.get('baseToken', {}).get('symbol', 'TOKEN')
            }
    except Exception as e:
        print(f"DexScreener API Error: {e}")
    return None

def calculate_score(data):
    score = 100
    honeypot = data.get("is_honeypot") == "1"
    tax = safe_float(data.get("buy_tax", 0)) + safe_float(data.get("sell_tax", 0))
    owner = data.get("can_take_back_ownership") == "1"
    mint = data.get("is_mintable") == "1"
    cooldown = data.get("is_trading_cooldown") == "1"
    hidden_tax = data.get("hidden_owner") == "1" or data.get("is_anti_whale") == "1"
    transfer_pausable = data.get("transfer_pausable") == "1"
    anti_whale = data.get("is_anti_whale") == "1"
    
    lp_holders = data.get("lp_holders", [])
    total_lp_locked = sum([safe_float(h.get("percent", 0)) for h in lp_holders if h.get("is_locked") == 1])
    lp_locked = total_lp_locked > 95
    
    holders = data.get("holders", [])[:10]
    holder_concentration = sum([safe_float(h.get("percent", 0)) for h in holders])
    whale_risk = holder_concentration > 50
    
    if honeypot: score -= 50
    if tax > 15: score -= 20
    elif tax > 5: score -= 10
    if owner: score -= 15
    if mint: score -= 10
    if not lp_locked: score -= 40 # Unlocked LP = instant rug risk
    if cooldown: score -= 10
    if hidden_tax: score -= 20
    if transfer_pausable: score -= 10
    if anti_whale: score -= 10
    if whale_risk: score -= 15
    
    return max(0, score), honeypot, tax, owner, mint, lp_locked, cooldown, hidden_tax, transfer_pausable, total_lp_locked, anti_whale, whale_risk

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global total_scans
    total_scans += 1
    
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/scan &lt;chain&gt; &lt;address&gt;</code>\nEx: <code>/scan base 0x1234...</code>", parse_mode='HTML')
        return
    
    chain_key = context.args[0].lower() if len(context.args) > 1 else "eth"
    token_addr = context.args[1] if len(context.args) > 1 else context.args[0]
    chain_id = CHAINS.get(chain_key, "1")
    dex_chain = DEX_CHAIN_MAP.get(chain_id, "ethereum")
    
    status_msg = await update.message.reply_text("⚔️ <code>RAEL_KERTIA: Analyzing...</code>", parse_mode='HTML')

    try:
        data, dex = await asyncio.gather(
            get_token_data(chain_id, token_addr),
            get_dexscreener_data(dex_chain, token_addr)
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ API Error: {str(e)[:50]}")
        return

    if not data:
        await status_msg.edit_text("❌ Token not found or unsupported chain.")
        return

    score, hp, tax, owner, mint, lp_l, cool, hidden, pause, lp_p, whale, whale_risk = calculate_score(data)
    
    verdict = "SAFE ✅" if score > 75 else "CAUTION ⚠️" if score > 45 else "RUG RISK 🚨"
    symbol = dex.get('symbol', 'TOKEN') if dex else 'TOKEN'
    holders = data.get("holder_count", "0")
    
    report = f"⚔️ <b>RAEL_KERTIA AUDIT: ${symbol}</b>\n<code>{token_addr[:6]}...{token_addr[-4:]}</code> | <code>{chain_key.upper()}</code>\n\n"
    report += f"🛡 <b>Score: {score}/100 | {verdict}</b>\n──────────────────────────────────\n"
    report += f"• <b>Honeypot:</b> {'🚨 YES' if hp else '✅ No'}\n"
    report += f"• <b>Taxes:</b> Buy/Sell <code>{tax}%</code> {'🚨' if tax > 15 else '⚠️' if tax > 5 else '✅'}\n"
    report += f"• <b>LP Locked:</b> <code>{lp_p:.1f}%</code> {'✅' if lp_l else '❌ UNLOCKED'}\n"
    report += f"• <b>Ownership:</b> {'⚠️ NOT RENOUNCED' if owner else '✅ Renounced'}\n"
    report += f"• <b>Hidden Tax:</b> {'🚨 DETECTED' if hidden else '✅ None'}\n"
    report += f"• <b>Anti-Whale:</b> {'⚠️ Enabled' if whale else '✅ None'}\n"
    report += f"• <b>Mintable:</b> {'🚨 YES' if mint else '✅ No'}\n"
    report += f"• <b>Cooldown:</b> {'⚠️ BOT TRAP' if cool else '✅ None'}\n"
    report += f"• <b>Whale Risk:</b> {'⚠️ HIGH' if whale_risk else '✅ Low'}\n"

    if dex:
        report += f"──────────────────────────────────\n💰 <b>Live Alpha:</b>\n"
        report += f"• Price: <code>${format_price(dex['price'])}</code>\n"
        report += f"• 1h: <code>{'📈' if dex['priceChange1h'] > 0 else '📉'} {dex['priceChange1h']:+.1f}%</code> | 24h: <code>{dex['priceChange24h']:+.1f}%</code>\n"
        report += f"• Liquidity: <code>${dex['liquidity']:,.0f}</code> | Holders: <code>{holders}</code>\n"

    if hidden: report += f"\n⚠️ <b>Trojan didn't see this!</b> Hidden Tax detected.\n"
    if whale: report += f"⚠️ <b>Soft Honeypot:</b> Anti-whale limits selling.\n"
    if whale_risk: report += f"⚠️ <b>Whale Risk:</b> Top 10 hold >50%. Dump risk.\n"

    report += f"\n🛡 <i>Scanned by Rael_Kertia | Threats Neutralized: <code>{total_scans}</code></i>"

    chart_url = dex['url'] if dex else f"https://dexscreener.com/{dex_chain}/{token_addr}"
    buttons = [[
        InlineKeyboardButton("📊 Chart", url=chart_url),
        InlineKeyboardButton("🛡 GoPlus Report", url=f"https://gopluslabs.io/token-security/{chain_id}/{token_addr}")
    ]]
    
    await status_msg.edit_text(report, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)

async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: <code>/snipe &lt;chain&gt; &lt;0x...&gt;</code>", parse_mode='HTML')
        return
    
    if len(context.args) == 1:
        chain_key, token = "eth", context.args[0]
    else:
        chain_key, token = context.args[0].lower(), context.args[1]
    
    chain_id = CHAINS.get(chain_key, "1")
    dex_chain = DEX_CHAIN_MAP.get(chain_id, "ethereum")
    await update.message.reply_text(f"🎯 Loading sniper intel for <code>{token[:8]}...</code>", parse_mode='HTML')
    
    data, dex = await asyncio.gather(
        get_token_data(chain_id, token),
        get_dexscreener_data(dex_chain, token)
    )
    
    if not data:
        await update.message.reply_text("No security data. Token too new or dead.")
        return
    
    score, honeypot, tax, owner, mint, lp_locked, cooldown, hidden_tax, pausable, lp_pct, anti_whale, whale_risk = calculate_score(data)
    
    holders = data.get("holder_count", "0")
    creator_pct = safe_float(data.get("creator_percent", 0))
    buy_tax = safe_float(data.get("buy_tax", 0))
    sell_tax = safe_float(data.get("sell_tax", 0))
    top_holders = data.get("holders", [])[:3]
    
    lp_amount = dex['liquidity'] if dex else 0
    price = dex['price'] if dex else 0
    
    if score > 80 and not honeypot and lp_locked and creator_pct < 5 and not hidden_tax and lp_amount > 10000:
        snipe_verdict = "SEND IT 🚀"
    elif score > 50 and not honeypot and lp_amount > 5000:
        snipe_verdict = "CAUTION ⚠️"
    else:
        snipe_verdict = "SKIP 🚨"
    
    msg = f"🎯 <b>Sniper Intel: {snipe_verdict}</b>\n"
    msg += f"<b>Kertia:</b> <code>{score}/100</code>\n─────────────────────────────\n"
    msg += f"<code>Honeypot {'YES - DO NOT BUY' if honeypot else 'SAFE'}</code>\n"
    msg += f"<code>LP Locked {'YES ' + str(round(lp_pct,1)) + '%' if lp_locked else 'NO - INSTANT RUG'}</code>\n"
    msg += f"<code>LP Size ${lp_amount:,.0f} {'✅' if lp_amount > 20000 else '⚠️'}</code>\n"
    msg += f"<code>Price ${format_price(price)}</code>\n"
    msg += f"<code>Buy/Sell Tax {buy_tax}% / {sell_tax}%</code>\n"
    msg += f"<code>Hidden Tax {'YES - TROJAN MISSED' if hidden_tax else 'No'}</code>\n"
    msg += f"<code>Anti-Whale {'YES - SOFT HP' if anti_whale else 'No'}</code>\n"
    msg += f"<code>Owner {'CAN RUG' if owner else 'Renounced'}</code>\n"
    msg += f"<code>Creator {creator_pct}% {'- DUMP RISK' if creator_pct > 10 else ''}</code>\n\n"
    
    if top_holders:
        msg += "<b>Top 3 Holders:</b>\n"
        for i, h in enumerate(top_holders, 1):
            addr = h.get("address", "")[:6]
            pct = h.get("percent", "0")
            msg += f"<code>{i}. {addr}... - {pct}%</code>\n"
    
    if top_holders and safe_float(top_holders[0].get("percent", 100)) < 5:
        msg += f"\n💎 <b>SMART MONEY:</b> Top holder &lt;5% = Distributed\n"
    
    chart_url = dex['url'] if dex else f"https://dexscreener.com/{dex_chain}/{token}"
    msg += f"\n<a href='{chart_url}'>📊 DexScreener</a>"
    
    await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: <code>/price &lt;chain&gt; &lt;0x...&gt;</code>", parse_mode='HTML')
        return
    
    if len(context.args) == 1:
        chain_key, token = "eth", context.args[0]
    else:
        chain_key, token = context.args[0].lower(), context.args[1]
    
    dex_chain = DEX_CHAIN_MAP.get(CHAINS.get(chain_key, "1"), "ethereum")
    dex_data = await get_dexscreener_data(dex_chain, token)
    if not dex_data:
        await update.message.reply_text("No price data found. Token may not be listed yet.")
        return
    
    msg = f"💰 <b>Price Data: {chain_key.upper()}</b>\n\n"
    msg += f"<b>Price:</b> <code>${format_price(dex_data['price'])}</code>\n"
    msg += f"<b>1h:</b> <code>{'📈' if dex_data['priceChange1h'] > 0 else '📉'} {dex_data['priceChange1h']:+.2f}%</code>\n"
    msg += f"<b>24h:</b> <code>{'📈' if dex_data['priceChange24h'] > 0 else '📉'} {dex_data['priceChange24h']:+.2f}%</code>\n"
    msg += f"<b>Volume 24h:</b> <code>${dex_data['volume24h']:,.0f}</code>\n"
    msg += f"<b>Liquidity:</b> <code>${dex_data['liquidity']:,.0f}</code>\n"
    msg += f"<b>FDV:</b> <code>${dex_data['fdv']:,.0f}</code>\n"
    msg += f"<b>DEX:</b> <code>{dex_data['dexId']}</code>\n\n"
    msg += f"<a href='{dex_data['url']}'>📊 Chart</a>"
    
    await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query.startswith("0x") or len(query) < 40:
        return

    data, dex = await asyncio.gather(
        get_token_data("1", query),
        get_dexscreener_data("ethereum", query)
    )
    if not data:
        return

    score, honeypot, tax, owner, mint, lp_locked, cooldown, hidden_tax, _, lp_pct, anti_whale, whale_risk = calculate_score(data)
    verdict = "SAFE ✅" if score > 75 else "CAUTION ⚠️" if score > 45 else "RUG 🚨"
    price = format_price(dex['price']) if dex else "N/A"
    change1h = f"{dex['priceChange1h']:+.1f}%" if dex else ""
    
    title = f"Kertia: {verdict} ({score}/100) | ${price} {change1h}"
    desc = f"Tax: {tax}% | LP: {lp_pct:.0f}% Locked"
    if hidden_tax: desc += " | HIDDEN TAX"
    if anti_whale: desc += " | ANTI-WHALE"
    if honeypot: desc = "🚨 HONEYPOT DETECTED"
    
    msg_content = f"⚔️ <b>Rael_kertia Audit</b>\n"
    msg_content += f"<b>Score:</b> <code>{score}/100</code> <b>{verdict}</b>\n"
    msg_content += f"<b>Price:</b> <code>${price}</code> <code>{change1h}</code>\n"
    msg_content += f"<b>Tax:</b> <code>{tax}%</code> | <b>LP:</b> <code>{'LOCKED' if lp_locked else 'UNLOCKED'}</code>\n"
    if hidden_tax: msg_content += f"⚠️ <b>Hidden Tax - Trojan Missed This</b>\n"
    if anti_whale: msg_content += f"⚠️ <b>Anti-Whale - Soft Honeypot</b>\n"
    msg_content += f"\n<a href='https://dexscreener.com/ethereum/{query}'>Chart</a>"
    
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=title,
            description=desc,
            input_message_content=InputTextMessageContent(msg_content, parse_mode='HTML', disable_web_page_preview=True)
        )
    ]
    await update.inline_query.answer(results, cache_time=30)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "snipe_promo":
        await query.answer("Sniper module launching soon. Join @RaelKertia for early access.", show_alert=True)

print("RAEL_KERTIA: Building application...")
app = Application.builder().token(TOKEN).build()
print("RAEL_KERTIA: Application built")

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("scan", scan))
app.add_handler(CommandHandler("snipe", snipe))
app.add_handler(CommandHandler("price", price))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(InlineQueryHandler(inline_query))
print("RAEL_KERTIA: Handlers registered")

print("RAEL_KERTIA: Starting polling...")
app.run_polling()
print("RAEL_KERTIA: Polling stopped")
