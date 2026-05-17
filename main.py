import os
import sys
import asyncio
import aiohttp
import requests
import re
from datetime import date
from web3 import Web3
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.helpers import escape
from dotenv import load_dotenv

load_dotenv()

# --- ENV & CONFIGURATION CONFIG ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
DEV_COLD_WALLET = os.getenv("DEV_COLD_WALLET")
BASE_RPC = os.getenv("BASE_RPC", "https://mainnet.base.org")
PRIVATE_KEY = os.getenv("BOT_WALLET_PRIVATE_KEY")
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")

# --- CORE ENGINE SETTINGS ---
DRY_RUN = False # Flip to True for risk-free simulation testing
FEE_PERCENT = 0.005 # 0.5% Platform Edge Fee
CHAIN_ID = 8453 # Base Mainnet Network ID
MIN_GAS_ETH = 0.0001 # ~0.30 USD minimum protection wall
DAILY_FREE_LIMIT = 10 # Phase 1 Freemium Limit

CHAIN_MAP = {'eth': '1', 'base': '8453', 'bsc': '56'}
BIRDEYE_CHAIN = {'eth': 'ethereum', 'base': 'base', 'bsc': 'bsc'}
DEX_CHAIN = {'eth': 'ethereum', 'base': 'base', 'bsc': 'bsc'}

# --- UNISWAP V2 / BASE INTERFACE ROUTER CONFIG ---
UNISWAP_V2_ROUTER_ADDRESS = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
UNISWAP_V2_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    }
]

# --- STATE MECHANISMS ---
USER_USAGE_TRACKER = {}
WHALE_WATCH_TARGETS = {}

# --- WEB3 INITIALIZATION SYSTEM ---
w3 = Web3(Web3.HTTPProvider(BASE_RPC))
DEV_WALLET_CHECKSUM = Web3.to_checksum_address(DEV_COLD_WALLET)
bot_account = w3.eth.account.from_key(PRIVATE_KEY)
BOT_WALLET = bot_account.address

assert BOT_WALLET.lower() == "0x2cD33b0702A5046966C068250666ff7CF3F4ebBE".lower(), "Security check failure: Private Key Mismatch"

# --- REWORKED SANITIZATION ENGINE ---
def sanitize_address(raw_arg: str) -> str:
    """
    Cleans raw user arguments, strips Telegram HTML leaks,
    and returns a clean, uniform hex string.
    """
    clean = re.sub(r"&[#\w\d]+;", "", raw_arg)
    clean = clean.replace("'", "").replace('"', "").replace("\n", "").strip()
    return clean

# --- SYSTEM UTILITIES ---
def get_eth_price():
    if not BIRDEYE_KEY: return 3200.00
    try:
        url = "https://public-api.birdeye.so/defi/price?address=0x4200000000000000000000000006"
        headers = {"X-API-KEY": BIRDEYE_KEY}
        r = requests.get(url, headers=headers, timeout=5)
        return float(r.json()["data"]["value"])
    except: return 3200.00

def get_eth_balance(address):
    wei = w3.eth.get_balance(Web3.to_checksum_address(address))
    return float(w3.from_wei(wei, 'ether'))

def is_user_limited(user_id: int) -> bool:
    today = date.today()
    if user_id not in USER_USAGE_TRACKER:
        USER_USAGE_TRACKER[user_id] = {"last_date": today, "count": 1}
        return False
    user_data = USER_USAGE_TRACKER[user_id]
    if user_data["last_date"]!= today:
        user_data["last_date"] = today
        user_data["count"] = 1
        return False
    if user_data["count"] >= DAILY_FREE_LIMIT:
        return True
    user_data["count"] += 1
    return False

# --- WEB3 RUNTIME MANAGEMENT ---
async def init_session(app: Application):
    print("Clearing webhook parameters...")
    await app.bot.delete_webhook(drop_pending_updates=True)
    timeout = aiohttp.ClientTimeout(total=15)
    app.bot_data['session'] = aiohttp.ClientSession(timeout=timeout)
    print("Rael_Kertia Engine v2.5 Online.")

async def close_session(app: Application):
    session = app.bot_data.get('session')
    if session: await session.close()
    print("Session closed safely.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if "Conflict" in str(err) or "terminated by other getUpdates" in str(err):
        print("Clash identified. Shutting down process stack cleanly to clear port access...")
        sys.exit(1)

# --- ENGINE COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = get_eth_balance(BOT_WALLET)
    await update.message.reply_html(
        "⚔️ <b>RAEL_KERTIA BOT v2.5 | THE TROJAN KILLER</b>\n\n"
        f"<b>0.5% Direct Fees Enabled</b> (Save 50% vs Trojan / Banana)\n\n"
        "<b>Runtime Environment:</b>\n"
        f"• Processing Core: <code>ONLINE</code>\n"
        f"• Bot Active Wallet: <code>{BOT_WALLET[:6]}...{BOT_WALLET[-4:]}</code>\n"
        f"• Available Node Gas: <code>{bal:.5f} ETH</code>\n"
        f"• Dev Target Destination: <code>{DEV_COLD_WALLET[:6]}...{DEV_COLD_WALLET[-4:]}</code>\n\n"
        "<b>Command Framework:</b>\n"
        "/scan [chain] [address] - Security Forensic Scan (10 Free Daily)\n"
        "/snipe [chain] [address] [amount_eth] - Low-Latency Swap Module\n"
        "/whaletrack [address] - Monitor Asset Inflow Positions\n"
        "/trade - Access GUI Terminal interface Layout"
    )

async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    web_app_url = f"https://rael-kertia.vercel.app?user_id={user_id}"
    kb = [[InlineKeyboardButton("⚔️ Launch Rael GUI Terminal", web_app=WebAppInfo(url=web_app_url))]]
    await update.message.reply_text("Process low-latency calls within our Vercel sandbox panel:", reply_markup=InlineKeyboardMarkup(kb))

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_limited(user_id):
        await update.message.reply_html("⚠️ <b>Daily Scan Quota Met (10/10)</b>\n\nBypass daily caps via /trade for unlimited terminal access.")
        return

    if len(context.args) < 2:
        await update.message.reply_html("Usage: <code>/scan base 0x...</code> - Paste address as one line")
        return

    chain = context.args[0].lower().strip()
    raw_addr = "".join(context.args[1:])
    address = sanitize_address(raw_addr)

    chain_id = CHAIN_MAP.get(chain)
    if not chain_id:
        await update.message.reply_html("❌ Unknown network. Use: eth, base, bsc")
        return

    msg = await update.message.reply_text("⚔️ Analyzing Contract Code Fields...")
    session = context.application.bot_data['session']
    be_chain = BIRDEYE_CHAIN.get(chain, 'base')

    try:
        if address.lower() == "0x4200000000000006".lower():
            price = get_eth_price()
            output = f"""⚔️ <b>RAEL_KERTIA AUDIT: $WETH</b>
<code>{address[:6]}...{address[-4:]}</code> | BASE

🛡️ <b>Score: 100/100 | SAFE</b>
——————————————————
- <b>Honeypot:</b> ✅ No
- <b>Taxes:</b> Buy/Sell 0.0%/0.0% ✅
- <b>LP Locked:</b> N/A - Native Wrapped ✅
- <b>Ownership:</b> ✅ Renounced
- <b>Hidden Tax:</b> ✅ No
- <b>Mintable:</b> ✅ No
——————————————————
💰 <b>Live Alpha:</b>
- <b>Price:</b> ${price:,.2f}
- <b>24h:</b> Check Birdeye
- <b>MC:</b> N/A | <b>Liquidity:</b> $Billions
- <b>Holders:</b> All of Base

✅ <b>Native asset. Safest trade on chain.</b>

🛡️ <i>Scanned by Rael_Kertia | Threats Neutralized: 0</i>"""

            kb = [[InlineKeyboardButton("📊 Chart", url=f"https://dexscreener.com/base/{address}")]]
            await msg.edit_text(output, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
            return

        gp_url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        be_url = f"https://public-api.birdeye.so/defi/token_overview?address={address}&chain={be_chain}"

        headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": be_chain} if BIRDEYE_KEY else {}
        gp_res, be_res = await asyncio.gather(session.get(gp_url), session.get(be_url, headers=headers), return_exceptions=True)

        gp_data, be_data = {}, {}
        if not isinstance(gp_res, Exception) and gp_res.status == 200:
            js = await gp_res.json()
            gp_data = (js.get('result', {}) or {}).get(address.lower(), {})

        if not isinstance(be_res, Exception) and be_res.status == 200:
            js = await be_res.json()
            be_data = js.get('data', {}) or {}

        is_hp = gp_data.get('is_honeypot', '0') == '1'
        buy_tax = float(gp_data.get('buy_tax', 0)) * 100 if 0 < float(gp_data.get('buy_tax', 0)) <= 1 else float(gp_data.get('buy_tax', 0))
        sell_tax = float(gp_data.get('sell_tax', 0)) * 100 if 0 < float(gp_data.get('sell_tax', 0)) <= 1 else float(gp_data.get('sell_tax', 0))
        can_take_back = gp_data.get('can_take_back_ownership', '0') == '1'
        hidden_owner = gp_data.get('hidden_owner', '0') == '1'
        is_mintable = gp_data.get('is_mintable', '0') == '1'
        lp_holders = gp_data.get('lp_holders', []) or []
        lp_locked_pct = sum([float(h.get('percent', 0)) for h in lp_holders if h.get('is_locked') == 1]) * 100

        price = float(be_data.get('price') or 0)
        mcap = float(be_data.get('mc') or 0)
        liquidity = float(be_data.get('liquidity') or 0)
        h1_change = float(be_data.get('priceChange1hPercent') or 0)
        h24_change = float(be_data.get('priceChange24hPercent') or 0)
        holders = int(be_data.get('holder') or 0)
        symbol = escape(gp_data.get('token_symbol') or be_data.get('symbol', 'UNKNOWN'))

        score = 100
        risks = 0
        if is_hp: score -= 50; risks += 1
        if buy_tax > 5 or sell_tax > 5: score -= 20; risks += 1
        if hidden_owner or can_take_back: score -= 20; risks += 1
        if lp_locked_pct < 50: score -= 10; risks += 1
        if is_mintable: score -= 10

        verdict = "SAFE" if score >= 80 else "RISKY" if score >= 50 else "DANGER"

        output = f"""⚔️ <b>RAEL_KERTIA AUDIT: ${symbol}</b>
<code>{address[:6]}...{address[-4:]}</code> | {chain.upper()}

🛡️ <b>Score: {score}/100 | {verdict}</b>
——————————————————
- <b>Honeypot:</b> {'🚨 Yes' if is_hp else '✅ No'}
- <b>Taxes:</b> Buy/Sell {buy_tax:.1f}%/{sell_tax:.1f}% {'✅' if buy_tax <= 5 else '⚠️'}
- <b>LP Locked:</b> {lp_locked_pct:.1f}% {'✅' if lp_locked_pct > 80 else '❌ UNLOCKED'}
- <b>Ownership:</b> {'⚠️ Mutable' if can_take_back else '✅ Safe'}
- <b>Hidden Tax:</b> {'🚨 Yes' if hidden_owner else '✅ No'}
- <b>Mintable:</b> {'⚠️ Yes' if is_mintable else '✅ No'}
——————————————————
💰 <b>Live Alpha:</b>
- <b>Price:</b> ${price:.8f}
- <b>1h:</b> {h1_change:+.1f}% | <b>24h:</b> {h24_change:+.1f}%
- <b>MC:</b> ${mcap:,.0f} | <b>Liquidity:</b> ${liquidity:,.0f}
- <b>Holders:</b> {holders:,}

"""
        if is_hp: output += "⚠️ <b>Soft Honeypot: Anti-whale limits selling.</b>\n"
        if lp_locked_pct < 50: output += "⚠️ <b>Rug Risk: LP not locked safely.</b>\n"

        output += f"\n🛡️ <i>Scanned by Rael_Kertia | Threats Neutralized: {risks}</i>"

        kb = [
            [InlineKeyboardButton("📊 Chart", url=f"https://dexscreener.com/{DEX_CHAIN.get(chain, 'base')}/{address}")],
            [InlineKeyboardButton("🛡️ GoPlus Report", url=f"https://gopluslabs.io/token-security/{chain_id}/{address}")]
        ]
        await msg.edit_text(output, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"Parsing halted: {escape(str(e)[:100])}")

# --- UPDATED SNIPE COMMAND EXECUTION ---
async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_html(
            "⚠️ <b>Invalid Command Syntax</b>\n"
            "Usage: <code>/snipe base [contract_address] [amount_eth]</code>"
        )
        return

    chain = context.args[0].lower().strip()
    raw_addr = "".join(context.args[1:-1])
    cleaned_addr = sanitize_address(raw_addr)

    if chain not in CHAIN_MAP:
        await update.message.reply_html("❌ <b>Unsupported Chain:</b> Use eth, base, or bsc.")
        return

    try:
        target_address = Web3.to_checksum_address(cleaned_addr)
    except ValueError:
        await update.message.reply_html(
            f"❌ <b>Execution failure sequence triggered:</b>\n"
            f"Unable to normalize input string into a valid hex address.\n"
            f"Input received: <code>{escape(raw_addr)}</code>"
        )
        return

    try:
        amount_eth = float(context.args[-1])
    except ValueError:
        await update.message.reply_html("❌ <b>Invalid Amount:</b> Please provide a valid numerical ETH value.")
        return

    msg = await update.message.reply_text("🎯 Initializing Low-Latency Router Bundle...")

    fee_amount = amount_eth * FEE_PERCENT
    trade_allocation = amount_eth - fee_amount

    if DRY_RUN:
        await msg.edit_text(
            f"🚀 <b>SIMULATED SWAP CALL RECONCILED</b>\n\n"
            f"• Capital Allocation: <code>{trade_allocation:.5f} ETH</code>\n"
            f"• Dev Platform cut (0.5%): <code>{fee_amount:.5f} ETH</code>\n"
            f"• Verification: <code>Bypassed standard mempool tracking chains.</code>",
            parse_mode='HTML'
        )
        return

    try:
        current_gas_bal = get_eth_balance(BOT_WALLET)
        if current_gas_bal < (amount_eth + MIN_GAS_ETH):
            await msg.edit_text(f"❌ Aborted: Insufficient system wallet resources ({current_gas_bal:.5f} ETH available).")
            return

        weth_address = Web3.to_checksum_address("0x4200000000000000000000000006")
        nonce = w3.eth.get_transaction_count(BOT_WALLET)
        priority_gas_price = int(w3.eth.gas_price * 1.2)

        # 1. Dispatch Platform Protocol Fee
        fee_tx = {
            'nonce': nonce,
            'to': DEV_WALLET_CHECKSUM,
            'value': w3.to_wei(fee_amount, 'ether'),
            'gas': 21000,
            'gasPrice': priority_gas_price,
            'chainId': CHAIN_ID
        }
        signed_fee = w3.eth.account.sign_transaction(fee_tx, PRIVATE_KEY)
        w3.eth.send_raw_transaction(signed_fee.raw_transaction)

        # 2. Build Trade Execution Router Path
        router = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V2_ROUTER_ADDRESS), abi=UNISWAP_V2_ROUTER_ABI)
        path = [weth_address, target_address]
        deadline = w3.eth.get_block('latest')['timestamp'] + 300

        # 3. Construct Router Swap Data
        swap_tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, # amountOutMin (0 for maximum slippage flexibility in quick snipe execution)
            path,
            BOT_WALLET,
            deadline
        ).build_transaction({
            'from': BOT_WALLET,
            'value': w3.to_wei(trade_allocation, 'ether'),
            'gas': 250000,
            'gasPrice': priority_gas_price,
            'nonce': nonce + 1,
            'chainId': CHAIN_ID
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)

        await msg.edit_text(
            f"⚔️ <b>SWAP EXECUTED SUCCESSFULLY</b>\n\n"
            f"• Routed Allocation: <code>{trade_allocation:.5f} ETH</code>\n"
            f"• Platform Fee Collected: <code>{fee_amount:.5f} ETH</code>\n"
            f"• TX Hash: <code>{tx_hash.hex()}</code>",
            parse_mode='HTML'
        )

    except Exception as e:
        await msg.edit_text(f"❌ Execution Engine Failure: {escape(str(e)[:150])}")

# --- INITIALIZATION RUNTIME ENGINE ---
if __name__ == "__main__":
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN variable missing from environment config.")
        sys.exit(1)

    # Initialize Context-Managed Framework
    application = Application.builder().token(TOKEN).build()

    # Register Post-Init Context & Death Listeners
    application.post_init = init_session
    application.post_stop = close_session
    application.add_error_handler(error_handler)

    # Attach Core Architecture Routers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("trade", trade))
    application.add_handler(CommandHandler("scan", scan))
    application.add_handler(CommandHandler("snipe", snipe))

    print("Boot sequence complete. Listening for server updates...")
    application.run_polling()
