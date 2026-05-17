import os
import sys
import asyncio
import aiohttp
import requests
import re
import json
from datetime import date
from web3 import Web3
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.helpers import escape
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

# --- ENV & CONFIGURATION ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
DEV_COLD_WALLET = os.getenv("DEV_COLD_WALLET")
BASE_RPC = os.getenv("BASE_RPC")
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# --- CORE ENGINE SETTINGS ---
DRY_RUN = False
FEE_PERCENT = 0.005
CHAIN_ID = 8453
MIN_GAS_ETH = 0.0001
DAILY_FREE_LIMIT = 10

CHAIN_MAP = {'eth': '1', 'base': '8453', 'bsc': '56'}
BIRDEYE_CHAIN = {'eth': 'ethereum', 'base': 'base', 'bsc': 'bsc'}
DEX_CHAIN = {'eth': 'ethereum', 'base': 'base', 'bsc': 'bsc'}

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

WETH_ADDRESS_CORRECT = "0x4200000000000000000006"

USER_USAGE_TRACKER = {}
USER_DB_FILE = "users.json"

w3 = Web3(Web3.HTTPProvider(BASE_RPC))
DEV_WALLET_CHECKSUM = Web3.to_checksum_address(DEV_COLD_WALLET)
fernet = Fernet(ENCRYPTION_KEY.encode())

# --- USER WALLET MANAGEMENT ---
def load_users():
    try:
        with open(USER_DB_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_users(data):
    with open(USER_DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_user_wallet(user_id: int):
    users = load_users()
    user_str = str(user_id)
    if user_str not in users:
        return None, None
    enc_pk = users[user_str]['pk'].encode()
    pk = fernet.decrypt(enc_pk).decode()
    address = users[user_str]['address']
    return pk, address

# --- UTILITIES ---
def sanitize_address(raw_arg: str) -> str:
    clean = re.sub(r"&[#\w\d]+;", "", raw_arg)
    clean = clean.replace("'", "").replace('"', "").replace("\n", "").strip()
    return clean

def safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def get_eth_price():
    if not BIRDEYE_KEY: return 3200.00
    try:
        url = f"https://public-api.birdeye.so/defi/price?address={WETH_ADDRESS_CORRECT}"
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

async def init_session(app: Application):
    print("Clearing webhook parameters...")
    await app.bot.delete_webhook(drop_pending_updates=True)
    timeout = aiohttp.ClientTimeout(total=15)
    app.bot_data['session'] = aiohttp.ClientSession(timeout=timeout)
    print("Rael_Kertia Engine v3.1 Online.")

async def close_session(app: Application):
    session = app.bot_data.get('session')
    if session: await session.close()
    print("Session closed safely.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if "Conflict" in str(err) or "terminated by other getUpdates" in str(err):
        print("Clash identified. Shutting down process stack cleanly...")
        sys.exit(1)

# --- ENGINE COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "⚔️ <b>RAEL_KERTIA BOT v3.1 | PUBLIC READY</b>\n\n"
        "<b>0.5% Fees | Per-User Wallets</b>\n\n"
        "<b>Commands:</b>\n"
        "/setup - Create your personal trading wallet\n"
        "/wallet - View your wallet address & balance\n"
        "/scan [chain] [address] - Security Audit\n"
        "/snipe [chain] [address] [amount_eth] - Execute Trade\n"
        "/trade - Launch GUI Terminal"
    )

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pk, address = get_user_wallet(user_id)
    if address:
        await update.message.reply_html(f"✅ Wallet exists:\n<code>{address}</code>\n\nUse /wallet to check balance.")
        return

    account = w3.eth.account.create()
    enc_pk = fernet.encrypt(account.key.hex().encode()).decode()

    users = load_users()
    users[str(user_id)] = {'address': account.address, 'pk': enc_pk}
    save_users(users)

    await update.message.reply_html(
        "⚔️ <b>Wallet Created Successfully</b>\n\n"
        f"Address: <code>{account.address}</code>\n\n"
        "1. Deposit Base ETH to this address to trade\n"
        "2. Your key is encrypted. We cannot see it\n"
        "3. Use /wallet to check balance\n\n"
        "<b>⚠️ FUND THIS WALLET BEFORE SNIPING</b>"
    )

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pk, address = get_user_wallet(user_id)
    if not address:
        await update.message.reply_html("❌ No wallet found. Use /setup to create one.")
        return
    bal = get_eth_balance(address)
    await update.message.reply_html(
        f"⚔️ <b>Your Rael Wallet</b>\n\n"
        f"Address: <code>{address}</code>\n"
        f"Balance: <code>{bal:.5f} ETH</code>\n\n"
        "Deposit Base ETH to this address to start trading."
    )

async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    web_app_url = f"https://rael-kertia.vercel.app?user_id={user_id}"
    kb = [[InlineKeyboardButton("⚔️ Launch Rael GUI Terminal", web_app=WebAppInfo(url=web_app_url))]]
    await update.message.reply_text("Access dashboard:", reply_markup=InlineKeyboardMarkup(kb))

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_limited(user_id):
        await update.message.reply_html("⚠️ <b>Daily Scan Quota Met (10/10)</b>")
        return

    if len(context.args) < 2:
        await update.message.reply_html("Usage: <code>/scan base 0x...</code>")
        return

    chain = context.args[0].lower().strip()
    raw_addr = "".join(context.args[1:])
    address = sanitize_address(raw_addr)

    chain_id = CHAIN_MAP.get(chain)
    if not chain_id:
        await update.message.reply_html("❌ Unknown network.")
        return

    msg = await update.message.reply_text("⚔️ Analyzing Contract...")
    session = context.application.bot_data['session']
    be_chain = BIRDEYE_CHAIN.get(chain, 'base')

    try:
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

        # GoPlus fields
        is_hp = gp_data.get('is_honeypot', '0') == '1'
        buy_tax = safe_float(gp_data.get('buy_tax', 0)) * 100
        sell_tax = safe_float(gp_data.get('sell_tax', 0)) * 100
        can_take_back = gp_data.get('can_take_back_ownership', '0') == '1'
        hidden_owner = gp_data.get('hidden_owner', '0') == '1'
        is_mintable = gp_data.get('is_mintable', '0') == '1'
        is_anti_whale = gp_data.get('is_anti_whale', '0') == '1'
        has_trading_cooldown = gp_data.get('trading_cooldown', '0') == '1'
        personal_slippage_modifiable = gp_data.get('personal_slippage_modifiable', '0') == '1'
        lp_holders = gp_data.get('lp_holders', []) or []
        lp_locked_pct = sum([safe_float(h.get('percent', 0)) for h in lp_holders if h.get('is_locked') == 1]) * 100

        # BirdEye fields
        price = safe_float(be_data.get('price'))
        mcap = safe_float(be_data.get('mc'))
        liquidity = safe_float(be_data.get('liquidity'))
        symbol = escape(gp_data.get('token_symbol') or be_data.get('symbol', 'UNKNOWN'))
        change_1h = safe_float(be_data.get('priceChange1hPercent'))
        change_24h = safe_float(be_data.get('priceChange24hPercent'))
        holders = safe_float(be_data.get('holder'))

        # Scoring
        score = 100
        threats = 0
        if is_hp: score -= 50; threats += 1
        if buy_tax > 5 or sell_tax > 5: score -= 20; threats += 1
        if hidden_owner or can_take_back: score -= 20; threats += 1
        if lp_locked_pct < 50: score -= 10
        if is_mintable: score -= 10; threats += 1
        if personal_slippage_modifiable: score -= 10; threats += 1

        verdict = "SAFE" if score >= 80 else "RISKY" if score >= 50 else "DANGER"

        # Build output matching screenshot 4
        output = f"""⚔️ <b>RAEL_KERTIA AUDIT: ${symbol}</b>
<code>{address[:6]}...{address[-4:]}</code> | {chain.upper()}

🛡️ <b>Score: {score}/100 | {verdict}</b>
——————————————————
- <b>Honeypot:</b> {'🚨 Yes' if is_hp else '✅ No'}
- <b>Taxes:</b> Buy/Sell {buy_tax:.1f}%/{sell_tax:.1f}% {'✅' if buy_tax < 5 and sell_tax < 5 else '⚠️'}
- <b>LP Locked:</b> {lp_locked_pct:.1f}% {'❌ UNLOCKED' if lp_locked_pct < 50 else '✅'}
- <b>Ownership:</b> {'⚠️ 0x0000...0000' if can_take_back else '✅ Safe'}
- <b>Hidden Tax:</b> {'⚠️ Yes' if personal_slippage_modifiable else '✅ No'}
- <b>Anti-Whale:</b> {'⚠️ Enabled' if is_anti_whale else '✅ No'}
- <b>Mintable:</b> {'⚠️ Yes' if is_mintable else '✅ No'}
- <b>Cooldown:</b> {'⚠️ Yes' if has_trading_cooldown else '✅ None'}
- <b>Whale Risk:</b> {'⚠️ High' if is_anti_whale or sell_tax > 10 else '✅ Low'}
——————————————————
💰 <b>Live Alpha:</b>
- <b>Price:</b> ${price:.8f}
- <b>1h:</b> 📉 {change_1h:.1f}% | <b>24h:</b> {change_24h:.1f}%
- <b>MC:</b> ${mcap:,.0f} | <b>Liquidity:</b> ${liquidity:,.0f}
- <b>Holders:</b> {int(holders)}
"""

        # Add warnings if needed
        if is_anti_whale:
            output += f"\n⚠️ <b>Soft Honeypot:</b> Anti-whale limits selling."
        if lp_locked_pct < 50:
            output += f"\n⚠️ <b>Rug Risk:</b> LP not locked safely."

        output += f"\n\n🛡️ <i>Scanned by Rael_Kertia | Threats Neutralized: {threats}</i>"

        # Buttons
        kb = [
            [InlineKeyboardButton("📊 Chart", url=f"https://dexscreener.com/{DEX_CHAIN.get(chain, 'base')}/{address}")],
            [InlineKeyboardButton("🛡️ GoPlus Report", url=f"https://gopluslabs.io/token-security/{chain_id}/{address}")]
        ]

        await msg.edit_text(output, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"Scan failed: {escape(str(e)[:100])}")

# --- LOW-LATENCY SNIPE ENGINE WITH PER-USER WALLETS ---
async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_pk, user_address = get_user_wallet(user_id)

    if not user_address:
        await update.message.reply_html("❌ No wallet found. Use /setup first.")
        return

    if len(context.args) < 3:
        await update.message.reply_html("Usage: <code>/snipe base [contract] [amount_eth]</code>")
        return

    chain = context.args[0].lower().strip()
    raw_addr = "".join(context.args[1:-1])
    cleaned_addr = sanitize_address(raw_addr)

    if chain!= 'base':
        await update.message.reply_html("❌ Currently optimized only for Base mainnet.")
        return

    try:
        target_address = Web3.to_checksum_address(cleaned_addr)
    except ValueError:
        await update.message.reply_html(f"❌ Invalid address: <code>{escape(raw_addr)}</code>")
        return

    try:
        amount_eth = float(context.args[-1])
    except ValueError:
        await update.message.reply_html("❌ Invalid ETH amount.")
        return

    msg = await update.message.reply_text("🎯 Broadcasting bundle...")

    fee_amount = amount_eth * FEE_PERCENT
    trade_allocation = amount_eth - fee_amount

    if DRY_RUN:
        await msg.edit_text(f"🚀 [DRY_RUN] Ready: {trade_allocation:.4f} ETH")
        return

    try:
        current_gas_bal = get_eth_balance(user_address)
        if current_gas_bal < amount_eth:
            await msg.edit_text(f"❌ Aborted: Balance too low ({current_gas_bal:.5f} ETH). Use /wallet to deposit.")
            return

        weth_address = Web3.to_checksum_address(WETH_ADDRESS_CORRECT)

        # EIP-1559 Gas
        latest_block = w3.eth.get_block('latest')
        base_fee = latest_block['baseFeePerGas']
        max_priority_fee = w3.eth.max_priority_fee
        max_fee = int((base_fee * 1.5) + max_priority_fee)

        # Pending nonce for user wallet
        try:
            start_nonce = w3.eth.get_transaction_count(user_address, 'pending')
        except Exception as e:
            await msg.edit_text("❌ Chain sync error. Retry.")
            return

        # 1. Fee TX to dev wallet
        fee_tx = {
            'nonce': start_nonce,
            'to': DEV_WALLET_CHECKSUM,
            'value': w3.to_wei(fee_amount, 'ether'),
            'gas': 21000,
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': max_priority_fee,
            'chainId': CHAIN_ID
        }
        signed_fee = w3.eth.account.sign_transaction(fee_tx, user_pk)

        # 2. Swap TX
        router = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V2_ROUTER_ADDRESS), abi=UNISWAP_V2_ROUTER_ABI)
        path = [weth_address, target_address]
        deadline = latest_block['timestamp'] + 300

        swap_tx_params = {
            'from': user_address,
            'value': w3.to_wei(trade_allocation, 'ether'),
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': max_priority_fee,
            'nonce': start_nonce + 1,
            'chainId': CHAIN_ID
        }

        try:
            estimated_gas = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
                0, path, user_address, deadline
            ).estimate_gas(swap_tx_params)
            swap_tx_params['gas'] = int(estimated_gas * 1.2)
        except:
            swap_tx_params['gas'] = 400000

        swap_tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, path, user_address, deadline
        ).build_transaction(swap_tx_params)

        signed_swap = w3.eth.account.sign_transaction(swap_tx, user_pk)

        # 3. Fire both
        fee_hash = w3.eth.send_raw_transaction(signed_fee.raw_transaction)
        swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)

        await msg.edit_text(
            f"⚔️ <b>BUNDLE SENT</b>\n\n"
            f"• Wallet: <code>{user_address[:6]}...{user_address[-4:]}</code>\n"
            f"• Amount: <code>{trade_allocation:.5f} ETH</code>\n"
            f"• TX: <code>{swap_hash.hex()}</code>",
            parse_mode='HTML'
        )

    except Exception as e:
        await msg.edit_text(f"❌ Execution Failed: {escape(str(e)[:150])}")

if __name__ == "__main__":
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN missing.")
        sys.exit(1)
    if not ENCRYPTION_KEY:
        print("Error: ENCRYPTION_KEY missing.")
        sys.exit(1)

    application = Application.builder().token(TOKEN).build()
    application.post_init = init_session
    application.post_stop = close_session
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setup", setup))
    application.add_handler(CommandHandler("wallet", wallet))
    application.add_handler(CommandHandler("trade", trade))
    application.add_handler(CommandHandler("scan", scan))
    application.add_handler(CommandHandler("snipe", snipe))

    print("Boot sequence complete. Polling...")
    application.run_polling()
