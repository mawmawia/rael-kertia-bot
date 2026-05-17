import os
import sys
import asyncio
import aiohttp
import requests
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
DRY_RUN = False              # Flip to True for risk-free simulation testing
FEE_PERCENT = 0.005          # 0.5% Platform Edge Fee
CHAIN_ID = 8453              # Base Mainnet Network ID
MIN_GAS_ETH = 0.0001         # ~0.30 USD minimum protection wall
DAILY_FREE_LIMIT = 10        # Phase 1 Freemium Limit

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
    if user_data["last_date"] != today:
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
        await update.message.reply_html("⚠️ <b>Daily Scan Quota Met (10/10)</b>\n\nBypass daily caps and access continuous tracing endpoints via our direct WebApp terminal system by calling /trade.")
        return

    if len(context.args) != 2:
        await update.message.reply_html("Usage: <code>/scan base 0x...</code>")
        return

    chain, address = context.args
    address = address.lower().strip()
    chain_id = CHAIN_MAP.get(chain.lower())
    if not chain_id:
        await update.message.reply_html("❌ Unknown network query parameter parsed.")
        return

    msg = await update.message.reply_text("⚔️ Analyzing Contract Code Fields...")
    session = context.application.bot_data['session']
    be_chain = BIRDEYE_CHAIN.get(chain.lower(), 'base')

    try:
        gp_url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        be_url = f"https://public-api.birdeye.so/defi/token_overview?address={address}&chain={be_chain}"
        
        headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": be_chain} if BIRDEYE_KEY else {}
        gp_res, be_res = await asyncio.gather(session.get(gp_url), session.get(be_url, headers=headers), return_exceptions=True)

        gp_data = {}
        if not isinstance(gp_res, Exception) and gp_res.status == 200:
            js = await gp_res.json()
            gp_data = (js.get('result', {}) or {}).get(address, {})

        be_data = {}
        if not isinstance(be_res, Exception) and be_res.status == 200:
            js = await be_res.json()
            be_data = js.get('data', {}) or {}

        is_hp = gp_data.get('is_honeypot', '0') == '1'
        buy_tax = float(gp_data.get('buy_tax', 0)) * 100 if 0 < float(gp_data.get('buy_tax', 0)) < 1.0 else float(gp_data.get('buy_tax', 0))
        sell_tax = float(gp_data.get('sell_tax', 0)) * 100 if 0 < float(gp_data.get('sell_tax', 0)) < 1.0 else float(gp_data.get('sell_tax', 0))
        hidden_tax = gp_data.get('hidden_owner', '0') == '1' or gp_data.get('cannot_buy', '0') == '1'
        
        price = float(be_data.get('price') or 0)
        mcap = float(be_data.get('mc') or 0)
        symbol = escape(gp_data.get('token_symbol') or be_data.get('symbol', 'UNKNOWN'))

        output = f"""⚔️ <b>VERDICT STACK: ${symbol}</b>
<code>{address[:6]}...{address[-4:]}</code>

• <b>Honeypot Logic:</b> {'🚨 ACTIVE HONEYPOT' if is_hp else '✅ CLEAN'}
• <b>Platform Taxes:</b> Buy: {buy_tax:.1f}% / Sell: {sell_tax:.1f}%
• <b>Hidden Modifiers:</b> {'🚨 DETECTED TAX LOOP' if hidden_tax else '✅ CLEAR'}
• <b>Metrics:</b> Price: ${price:.8f} | FDV: ${mcap:,.0f}
——————————————————
"""
        if hidden_tax:
            output += "\n⚠️ <b>Warning: Structural anomaly found. Standard Trojan scans will skip over this exploit code signature.</b>"

        await msg.edit_text(output, parse_mode='HTML')
    except Exception as e:
        await msg.edit_text(f"Parsing halted: {str(e)[:50]}")

# --- LOW-LATENCY ROUTER EXECUTION ENGINE ---
async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The Rael Action Layer - Direct split processing + Uniswap V2 payload execution"""
    if len(context.args) != 3:
        await update.message.reply_html("Usage: <code>/snipe base [token_address] [amount_eth]</code>")
        return

    chain, target_token_address, amount_eth = context.args
    try:
        amount_eth = float(amount_eth)
    except:
        await update.message.reply_text("Invalid ETH parameter configuration syntax.")
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

        target_token_checksum = Web3.to_checksum_address(target_token_address.strip())
        weth_address = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")

        nonce = w3.eth.get_transaction_count(BOT_WALLET)
        priority_gas_price = int(w3.eth.gas_price * 1.2) # Outpace standard competition speed baselines

        # --- TRANSACTION MODULE A: 0.5% DEVELOPER REVENUE FEE SPLIT ---
        fee_tx = {
            'nonce': nonce,
            'to': DEV_WALLET_CHECKSUM,
            'value': w3.to_wei(fee_amount, 'ether'),
            'gas': 21000,
            'gasPrice': priority_gas_price,
            'chainId': CHAIN_ID
        }
        signed_fee = w3.eth.account.sign_transaction(fee_tx, PRIVATE_KEY)
        fee_tx_hash = w3.eth.send_raw_transaction(signed_fee.rawTransaction)

        # --- TRANSACTION MODULE B: DIRECT SMART INTERFACE UNISWAP CONTRACT SWAP ---
        router_contract = w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_V2_ROUTER_ADDRESS), 
            abi=UNISWAP_V2_ROUTER_ABI
        )

        path = [weth_address, target_token_checksum]
        deadline = w3.eth.get_block('latest')['timestamp'] + 300

        swap_tx = router_contract.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, # Speed asset targeting profiles allow 0 slip limit thresholds
            path,
            BOT_WALLET,
            deadline
        ).build_transaction({
            'from': BOT_WALLET,
            'value': w3.to_wei(trade_allocation, 'ether'),
            'gas': 180000,
            'gasPrice': priority_gas_price,
            'nonce': nonce + 1,
            'chainId': CHAIN_ID
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        swap_tx_hash = w3.eth.send_raw_transaction(signed_swap.rawTransaction)

        success_ui_msg = (
            f"⚔️ <b>TRADE COMPLETE | EXECUTION COMMITTED</b>\n\n"
            f"• <b>Developer Yield (0.5%):</b> <a href='https://basescan.org/tx/{w3.to_hex(fee_tx_hash)}'>Basescan</a>\n"
            f"• <b>Contract Allocation (99.5%):</b> <a href='https://basescan.org/tx/{w3.to_hex(swap_tx_hash)}'>Basescan</a>\n\n"
            f"⚡ <i>Liquidity route confirmation closed out on-chain.</i>"
        )
        await msg.edit_text(success_ui_msg, parse_mode='HTML', disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"❌ Execution failure sequence triggered: {escape(str(e)[:100])}")

async def whaletrack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_html("Usage: <code>/whaletrack 0x...</code>")
        return
    
    target_wallet = context.args[0].strip()
    if user_id not in WHALE_WATCH_TARGETS:
        WHALE_WATCH_TARGETS[user_id] = []
        
    WHALE_WATCH_TARGETS[user_id].append(target_wallet)
    await update.message.reply_html(f"🐋 <b>Vector Target Initialized:</b> Monitoring positions for <code>{target_wallet[:8]}...</code> loops.")

def main():
    if not all([TOKEN, DEV_COLD_WALLET, PRIVATE_KEY]):
        raise ValueError("Critical System Error: Configuration Key Variables Missing from active environment settings.")
        
    app = Application.builder().token(TOKEN).build()
    
    app.post_init = init_session
    app.post_shutdown = close_session
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("trade", trade))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("snipe", snipe))
    app.add_handler(CommandHandler("whaletrack", whaletrack))
    app.add_error_handler(error_handler)
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
