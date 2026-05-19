import os
import sys
import logging
import asyncio
import uuid
import httpx
import sqlite3
from cryptography.fernet import Fernet
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, InlineQueryHandler, CallbackQueryHandler
from web3 import Web3

# ===== LOGGING =====
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("NexusIntel")
logger.info("📡 NEXUS INTEL: System initialization starting...")

# ===== ENV VARS - RAILWAY =====
TOKEN = os.environ.get('BOT_TOKEN')
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
DEV_COLD_WALLET = os.environ.get('DEV_COLD_WALLET')
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))

if not all([TOKEN, ENCRYPTION_KEY, DEV_COLD_WALLET]):
    logger.critical("❌ Core environment variables missing from Railway config panel!"); sys.exit(1)

FEE_PERCENT = 0.0035 # 0.35%
fernet = Fernet(ENCRYPTION_KEY.encode())
TOTAL_SCANS = 0

# ===== THREAD-SAFE DATABASE SETUP =====
def init_db():
    with sqlite3.connect("wallets.db") as local_conn:
        local_conn.execute("CREATE TABLE IF NOT EXISTS wallets (user_id INTEGER PRIMARY KEY, enc_key TEXT)")
        local_conn.commit()

init_db()

# ===== CHAINS =====
CHAINS = {"eth": "1", "base": "8453", "bsc": "56", "arb": "42161", "sol": "solana"}
DEX_CHAIN_MAP = {"1": "ethereum", "8453": "base", "56": "bsc", "42161": "arbitrum", "solana": "solana"}
RPC_MAP = {
    "1": "https://eth.llamarpc.com",
    "8453": "https://mainnet.base.org",
    "56": "https://bsc-dataseed.binance.org",
    "42161": "https://arb1.arbitrum.io/rpc"
}

# ===== WALLET UTILS (Thread-Safe Context) =====
def get_wallet(user_id: int):
    with sqlite3.connect("wallets.db") as local_conn:
        row = local_conn.execute("SELECT enc_key FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return Web3().eth.account.from_key(fernet.decrypt(row[0].encode()))
        acct = Web3().eth.account.create()
        enc = fernet.encrypt(acct.key).decode()
        local_conn.execute("INSERT INTO wallets VALUES (?,?)", (user_id, enc))
        local_conn.commit()
        return acct

def format_price(price):
    if price == 0: return "0.00"
    if price < 0.000001: return f"{price:.10f}"
    if price < 0.01: return f"{price:.6f}"
    if price < 1: return f"{price:.4f}"
    return f"{price:,.2f}"

# ===== API CALLS =====
async def get_token_data(chain_id, token):
    addr = token if chain_id == "solana" else token.lower()
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={addr}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, timeout=10.0)
            res_json = r.json()
            if res_json.get("code") == 1 and res_json.get("result"):
                return res_json["result"].get(addr)
        except Exception as e:
            logger.error(f"GoPlus Error: {e}")
    return None

async def get_dexscreener_data(dex_chain, token):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, timeout=7.0)
            pairs = r.json().get('pairs', [])
            for p in pairs:
                if p.get('chainId') == dex_chain:
                    return {
                        'price': float(p.get('priceUsd', 0)),
                        'priceChange1h': float(p.get('priceChange', {}).get('h1', 0)),
                        'priceChange24h': float(p.get('priceChange', {}).get('h24', 0)),
                        'volume24h': float(p.get('volume', {}).get('h24', 0)),
                        'liquidity': float(p.get('liquidity', {}).get('usd', 0)),
                        'fdv': float(p.get('fdv', 0)),
                        'url': p.get('url', f'https://dexscreener.com/{dex_chain}/{token}'),
                        'symbol': p.get('baseToken', {}).get('symbol', 'TOKEN')
                    }
        except Exception as e:
            logger.error(f"DexScreener Error: {e}")
    return None

def calculate_score(data):
    score = 100
    if not data: return 0, True, 0, True, True, False, False, True, False, 0
    honeypot = data.get("is_honeypot") == "1"
    tax = float(data.get("buy_tax", 0)) + float(data.get("sell_tax", 0))
    owner_control = data.get("can_take_back_ownership") == "1"
    mintable = data.get("is_mintable") == "1"
    hidden_tax = data.get("hidden_owner") == "1"
    anti_whale = data.get("is_anti_whale") == "1"
    lp_holders = data.get("lp_holders", [])
    total_lp_locked = sum([float(h.get("percent", 0)) for h in lp_holders if str(h.get("is_locked")) == "1" or h.get("is_locked") == 1])
    lp_locked = total_lp_locked > 80
    holders_list = data.get("holders", [])[:10]
    whale_concentration = sum([float(h.get("percent", 0)) for h in holders_list if h.get("percent")]) > 50
    if honeypot: score -= 50
    if tax > 15: score -= 20
    elif tax > 5: score -= 10
    if owner_control: score -= 15
    if mintable: score -= 10
    if not lp_locked: score -= 15
    if hidden_tax: score -= 20
    if anti_whale: score -= 10
    if whale_concentration: score -= 15
    return max(0, score), honeypot, tax, owner_control, mintable, lp_locked, hidden_tax, anti_whale, whale_concentration, total_lp_locked

# ===== BLOCKCHAIN BACKGROUND WORKERS - NO ASYNC BLOCK =====
def fetch_blockchain_balance(rpc_url, address):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    balance = w3.eth.get_balance(address)
    return w3.from_wei(balance, 'ether')

def broadcast_fee_transaction(rpc_url, to_address, value_wei, private_key, chain_id):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    nonce = w3.eth.get_transaction_count(account.address)
    tx = {
        'to': to_address,
        'value': value_wei,
        'gas': 21000,
        'nonce': nonce,
        'chainId': int(chain_id)
    }
    # EIP-1559 Support for L2 chains
    try:
        tx['maxPriorityFeePerGas'] = w3.eth.max_priority_fee_per_gas
        tx['maxFeePerGas'] = w3.eth.gas_price + tx['maxPriorityFeePerGas']
    except:
        tx['gasPrice'] = w3.eth.gas_price

    signed = account.sign_transaction(tx)
    return w3.eth.send_raw_transaction(signed.rawTransaction).hex()

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = get_wallet(update.effective_user.id)
    msg = "📡 **Nexus Intel Core v1.0.0**\n"
    msg += "High-speed multi-chain audit + execution.\n\n"
    msg += f"Your wallet: `{w.address}`\n"
    msg += "Deposit Base/ETH/BSC/Arb to start.\n\n"
    msg += "**Commands:**\n"
    msg += "/scan <chain> <address> - Contract analysis\n"
    msg += "/wallet - Show deposit address\n"
    msg += "/snipe <chain> <address> <amount> - Execute with 0.35% fee\n"
    msg += "/price <chain> <address> - Live market data\n\n"
    msg += "💡 **Inline:** `@bot_username base 0x...` in any group\n\n"
    msg += "_60% cheaper than competitors. DM-only execution._"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = get_wallet(update.effective_user.id)
    await update.message.reply_text(f"Deposit to:\n`{w.address}`\n\n⚠️ Gas + 0.35% fee auto-deducted per trade.", parse_mode="Markdown")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global TOTAL_SCANS
    if not context.args:
        await update.message.reply_text("❌ Usage: `/scan base 0x1234...`", parse_mode='Markdown')
        return
    chain_key = context.args[0].lower() if len(context.args) > 1 else "eth"
    token_addr = context.args[1] if len(context.args) > 1 else context.args[0]
    chain_id = CHAINS.get(chain_key, "1")
    dex_chain = DEX_CHAIN_MAP.get(chain_id, "ethereum")
    status_msg = await update.message.reply_text("📡 `Nexus Intel: Parsing data...`", parse_mode='Markdown')
    TOTAL_SCANS += 1
    data, dex = await asyncio.gather(get_token_data(chain_id, token_addr), get_dexscreener_data(dex_chain, token_addr))
    if not data:
        await status_msg.edit_text("❌ Unable to extract parameters. Check address/chain.")
        return
    score, hp, tax, owner, mint, lp_l, hidden, whale, whale_risk, lp_p = calculate_score(data)
    verdict = "EXCELLENT ✅" if score > 75 else "STABLE ⚠️" if score > 45 else "HIGH RISK 🚨"
    symbol = dex.get('symbol', 'TOKEN') if dex else 'TOKEN'
    report = f"📡 **Nexus Intel: ${symbol}**\n`{token_addr[:6]}...{token_addr[-4:]}` | `{chain_key.upper()}`\n\n"
    report += f"🛡 **Score: {score}/100 | {verdict}**\n──────────────────\n"
    report += f"• **Honeypot:** {'🚨 TRAPPED' if hp else '✅ Clear'}\n"
    report += f"• **Tax:** `{tax}%` {'🚨' if tax > 15 else '⚠️' if tax > 5 else '✅'}\n"
    report += f"• **LP Lock:** `{lp_p:.1f}%` {'✅' if lp_l else '❌ Risk'}\n"
    report += f"• **Owner:** {'⚠️ Has Control' if owner else 'Renounced ✅'}\n"
    report += f"• **Hidden Tax:** {'🚨 Active' if hidden else '✅ None'}\n"
    if dex:
        report += f"──────────────────\n📊 **Market:** ${format_price(dex['price'])} | 1h: `{dex['priceChange1h']:+.1f}%`\n"
        report += f"• Liquidity: `${dex['liquidity']:,.0f}`\n"
    report += f"──────────────────\n⚡ 0.35% execution fee | Scans: {TOTAL_SCANS}"
    chart_url = dex['url'] if dex else f"https://dexscreener.com/{dex_chain}/{token_addr}"
    buttons = [[InlineKeyboardButton("Execute 0.01", callback_data=f"snip_{chain_key}_{token_addr}_0.01")],
               [InlineKeyboardButton("📊 Chart", url=chart_url)]]
    await status_msg.edit_text(report, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)

async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # DM-ONLY LOCK
    if update.message.chat.type!= 'private':
        await update.message.reply_text("Execution locked to DM. Groups are scan-only.")
        return
    if len(context.args) < 3:
        await update.message.reply_text("❌ Usage: `/snipe base 0x... 0.01`", parse_mode='Markdown')
        return
    chain_key, token, amount_str = context.args[0].lower(), context.args[1], context.args[2]
    try: amount = float(amount_str)
    except: await update.message.reply_text("❌ Amount must be a valid number (e.g. 0.01)"); return
    if chain_key not in CHAINS or chain_key == "sol":
        await update.message.reply_text("❌ Supported chains: eth, base, bsc, arb. SOL integration coming soon."); return

    chain_id = CHAINS[chain_key]
    w = get_wallet(user_id)
    rpc_url = RPC_MAP[chain_id]

    status = await update.message.reply_text("⏳ `Checking ledger balances securely via threadpool...`", parse_mode='Markdown')

    try:
        # Secure offloading of network calls to stop blocking the main event loop
        balance_eth = await asyncio.to_thread(fetch_blockchain_balance, rpc_url, w.address)
        if balance_eth < amount:
            await status.edit_text(f"❌ Insufficient balance. Available: {balance_eth:.6f} ETH\nDeposit directly to your smart node: `{w.address}`", parse_mode="Markdown")
            return
    except Exception as e:
        await status.edit_text(f"❌ RPC Connection Error: {str(e)[:50]}")
        return

    # FEE CALC - OWNER BYPASS
    if user_id == OWNER_ID:
        fee = 0.0; swap_amount = amount
        msg = f"🎯 **OWNER TEST MODE**\nExecuting {amount} ETH on {chain_key.upper()}...\nFee: 0.00 ETH\n"
    else:
        fee = amount * FEE_PERCENT; swap_amount = amount - fee
        msg = f"🎯 **Executing {amount} ETH on {chain_key.upper()}**\nFee: {fee:.6f} ETH (0.35%)\nSwap routing weight: {swap_amount:.6f} ETH\n"

    await status.edit_text(msg + "⏳ Routing network tokens...", parse_mode='Markdown')

    try:
        if fee > 0:
            value_wei = Web3().to_wei(fee, 'ether')
            # Safely broadcast transaction on background thread
            fee_hash = await asyncio.to_thread(broadcast_fee_transaction, rpc_url, DEV_COLD_WALLET, value_wei, w.key, chain_id)
            logger.info(f"Platform fee extracted successfully: {fee_hash}")
            await asyncio.sleep(1)

        # 2. TODO: Inject Router Contract logic here for live exchange pathing (UniswapV2 / Aerodrome Router)
        await status.edit_text(f"✅ **Platform Fees Accounted For**\nChain: {chain_key.upper()}\nRouted Value: {swap_amount:.6f} ETH\nCollected Engine Fee: {fee:.6f} ETH\n\n⚠️ Core pipeline established. Inject target DEX routing arrays to process physical swaps.", parse_mode='Markdown')
    except Exception as e:
        await status.edit_text(f"❌ Pipeline Execution Refused: {str(e)[:100]}")

async def button_snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, chain, address, amount = q.data.split("_")
    context.args = [chain, address, amount]
    update.message = q.message
    await snipe(update, context)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/price base 0x...`", parse_mode='Markdown'); return
    chain_key = context.args[0].lower() if len(context.args) > 1 else "eth"
    token = context.args[1] if len(context.args) > 1 else context.args[0]
    dex_chain = DEX_CHAIN_MAP.get(CHAINS.get(chain_key, "1"), "ethereum")
    dex_data = await get_dexscreener_data(dex_chain, token)
    if not dex_data:
        await update.message.reply_text("❌ No token pool matches listed pair configurations."); return
    msg = f"📈 **Market Feed: {chain_key.upper()}**\n\n"
    msg += f"• Price: `${format_price(dex_data['price'])}`\n"
    msg += f"• 1h Run: `{dex_data['priceChange1h']:+.2f}%` | 24h: `{dex_data['priceChange24h']:+.2f}%`\n"
    msg += f"• Vol 24h: `${dex_data['volume24h']:,.0f}`\n"
    msg += f"• Liquidity: `${dex_data['liquidity']:,.0f}`\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().split()
    if len(query) < 2: return
    chain_key, address = query[0].lower(), query[1]
    chain_id = CHAINS.get(chain_key, "1")
    data = await get_token_data(chain_id, address)
    if not data: return
    score, hp, tax, _, _, _, _, _, _, lp_p = calculate_score(data)
    verdict = "VERIFIED ✅" if score > 75 else "ALERT 🚨"
    title = f"{chain_key.upper()} Scan: {verdict} ({score}/100)"
    desc = f"Tax: {tax}% | LP: {lp_p:.0f}% | 0.35% node execution fees"
    content = f"📡 **Nexus Intel Fast Scan**\n`{address[:10]}...` | {chain_key.upper()}\n"
    content += f"Score: `{score}/100` | **{verdict}**\n"
    content += f"Tax: `{tax}%` | LP Lock: `{lp_p:.1f}%`\n"
    content += f"⚡ Node Execution Node: 0.35% (65% cheaper than industry standards)"
    results = [InlineQueryResultArticle(id=str(uuid.uuid4()), title=title, description=desc,
               input_message_content=InputTextMessageContent(content, parse_mode='Markdown'),
               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Execute Private Trading Node", url=f"https://t.me/{context.bot.username}")]]))]
    await update.inline_query.answer(results, cache_time=10)

if __name__ == "__main__":
    logger.info("Initializing application processing channels...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("snipe", snipe))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CallbackQueryHandler(button_snipe, pattern="^snip_"))
    app.add_handler(InlineQueryHandler(inline_query))
    logger.info("Active pipeline connected. Polling operational event fields...")
    app.run_polling()
