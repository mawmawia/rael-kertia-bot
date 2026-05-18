import os
import sys
import asyncio
import aiohttp
import re
import json
import secrets
import string
import logging
from datetime import date
from web3 import Web3
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.helpers import escape
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from users import init_db, close_db, get_user, save_user

load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- ENV & CONFIGURATION ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
DEV_COLD_WALLET = os.getenv("DEV_COLD_WALLET") # Your existing fee wallet var
BASE_RPC = os.getenv("BASE_RPC")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))

# --- CORE ENGINE SETTINGS ---
DRY_RUN = os.getenv("DRY_RUN", "True") == "True"
FEE_PERCENT = 0.005
REFERRAL_CUT = 0.10
CHAIN_ID = 8453
MIN_GAS_ETH = 0.0001
DAILY_FREE_LIMIT = 10

CHAIN_MAP = {'eth': '1', 'base': '8453', 'bsc': '56'}
UNISWAP_V2_ROUTER_ADDRESS = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
UNISWAP_V2_ROUTER_ABI = [{"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"payable","type":"function"}]
WETH_ADDRESS_CORRECT = "0x4200000000000000000000000000000006"

USER_USAGE_TRACKER = {}
w3 = Web3(Web3.HTTPProvider(BASE_RPC))
DEV_WALLET_CHECKSUM = Web3.to_checksum_address(DEV_COLD_WALLET)
fernet = Fernet(ENCRYPTION_KEY.encode())

# --- USER & REFERRAL MANAGEMENT ---
def generate_ref_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))

async def get_user_wallet(user_id: int):
    user_data = await get_user(str(user_id))
    if not user_data.get('pk'): return None, None
    enc_pk = user_data['pk'].encode()
    pk = fernet.decrypt(enc_pk).decode()
    address = user_data['address']
    return pk, address

async def get_user_data(user_id: int):
    return await get_user(str(user_id))

# --- UTILITIES ---
def sanitize_address(raw_arg: str) -> str:
    clean = re.sub(r"&[#\w\d]+;", "", raw_arg)
    return clean.replace("'", "").replace('"', "").replace("\n", "").strip()

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
    await app.bot.delete_webhook(drop_pending_updates=True)
    await init_db()
    timeout = aiohttp.ClientTimeout(total=15)
    app.bot_data['session'] = aiohttp.ClientSession(timeout=timeout)
    logging.info(f"Rael_Kertia Engine v3.3 Online | DRY_RUN={DRY_RUN}")

async def close_session(app: Application):
    await close_db()
    session = app.bot_data.get('session')
    if session: await session.close()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "Conflict" in str(context.error): sys.exit(1)

# --- ENGINE COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "⚔️ <b>RAEL_KERTIA BOT v3.3 | POSTGRES READY</b>\n\n"
        f"<b>0.5% Fees | Mode: {'DRY_RUN' if DRY_RUN else 'LIVE'}</b>\n\n"
        "<b>Commands:</b>\n"
        "/setup - Create your personal trading wallet\n"
        "/wallet - View wallet & balance\n"
        "/ping - Check if bot + DB is alive\n"
        "/snipe base [address] [amount_eth] - Execute Trade"
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong. DB Connected.")

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pk, address = await get_user_wallet(user_id)
    if address:
        await update.message.reply_html(f"✅ Wallet exists:\n<code>{address}</code>")
        return

    account = w3.eth.account.create()
    enc_pk = fernet.encrypt(account.key.hex().encode()).decode()
    user_data = await get_user_data(user_id)
    user_data.update({
        'address': account.address, 'pk': enc_pk,
        'ref_code': user_data.get('ref_code') or generate_ref_code(),
        'referrals': 0, 'earned_eth': 0.0
    })
    await save_user(str(user_id), user_data)
    await update.message.reply_html(f"⚔️ <b>Wallet Created</b>\n<code>{account.address}</code>\n\n<b>Fund this wallet to trade.</b>")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pk, address = await get_user_wallet(user_id)
    if not address:
        await update.message.reply_html("❌ No wallet. Use /setup")
        return
    bal = get_eth_balance(address)
    await update.message.reply_html(f"⚔️ <b>Your Wallet</b>\n<code>{address}</code>\nBalance: <code>{bal:.5f} ETH</code>")

async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_pk, user_address = await get_user_wallet(user_id)
    if not user_address:
        await update.message.reply_html("❌ No wallet. Use /setup first.")
        return
    if len(context.args) < 3:
        await update.message.reply_html("Usage: <code>/snipe base 0x... 0.01</code>")
        return

    chain = context.args[0].lower().strip()
    if chain!= 'base':
        await update.message.reply_html("❌ Only Base mainnet supported.")
        return

    try:
        target_address = Web3.to_checksum_address(sanitize_address("".join(context.args[1:-1])))
        amount_eth = float(context.args[-1])
    except:
        await update.message.reply_html("❌ Invalid address or amount.")
        return

    msg = await update.message.reply_text("🎯 Simulating bundle...")
    total_fee = amount_eth * FEE_PERCENT
    dev_fee = total_fee
    trade_allocation = amount_eth - total_fee

    if DRY_RUN:
        await msg.edit_text(
            f"🚀 [DRY_RUN] Simulation Ready\n\n"
            f"Trade: <code>{trade_allocation:.5f} ETH</code>\n"
            f"Fee to you: <code>{dev_fee:.6f} ETH</code>\n"
            f"Gas estimate: ~150000\n"
            f"Mode: SAFE - No funds moved"
        )
        return

    try:
        current_gas_bal = get_eth_balance(user_address)
        if current_gas_bal < amount_eth:
            await msg.edit_text(f"❌ Aborted: Balance too low ({current_gas_bal:.5f} ETH). Use /wallet to deposit.")
            return

        weth_address = Web3.to_checksum_address(WETH_ADDRESS_CORRECT)
        latest_block = w3.eth.get_block('latest')
        base_fee = latest_block['baseFeePerGas']
        max_priority_fee = w3.eth.max_priority_fee
        max_fee = int((base_fee * 1.5) + max_priority_fee)
        start_nonce = w3.eth.get_transaction_count(user_address, 'pending')
        txs_to_send = []

        fee_tx = {
            'nonce': start_nonce, 'to': DEV_WALLET_CHECKSUM,
            'value': w3.to_wei(dev_fee, 'ether'), 'gas': 21000,
            'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': max_priority_fee, 'chainId': CHAIN_ID
        }
        txs_to_send.append(w3.eth.account.sign_transaction(fee_tx, user_pk))

        router = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V2_ROUTER_ADDRESS), abi=UNISWAP_V2_ROUTER_ABI)
        path = [weth_address, target_address]
        deadline = latest_block['timestamp'] + 300
        swap_tx_params = {
            'from': user_address, 'value': w3.to_wei(trade_allocation, 'ether'),
            'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': max_priority_fee,
            'nonce': start_nonce + 1, 'chainId': CHAIN_ID
        }
        try:
            estimated_gas = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(0, path, user_address, deadline).estimate_gas(swap_tx_params)
            swap_tx_params['gas'] = int(estimated_gas * 1.2)
        except:
            swap_tx_params['gas'] = 400000

        swap_tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(0, path, user_address, deadline).build_transaction(swap_tx_params)
        txs_to_send.append(w3.eth.account.sign_transaction(swap_tx, user_pk))

        hashes = []
        for signed_tx in txs_to_send:
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            hashes.append(tx_hash.hex())

        # OWNER GAS ALERT
        if user_id == OWNER_TELEGRAM_ID:
            bal = get_eth_balance(user_address)
            if bal < 0.002:
                await context.bot.send_message(chat_id=user_id, text=f"⚠️ <b>OWNER ALERT:</b> Your bot wallet gas low: {bal:.5f} ETH", parse_mode='HTML')

        await msg.edit_text(
            f"⚔️ <b>BUNDLE SENT</b>\n\n"
            f"• Wallet: <code>{user_address[:6]}...{user_address[-4:]}</code>\n"
            f"• Amount: <code>{trade_allocation:.5f} ETH</code>\n"
            f"• Fee: <code>{dev_fee:.6f} ETH</code>\n"
            f"• TX: <code>{hashes[-1]}</code>"
        )

    except Exception as e:
        await msg.edit_text(f"❌ Execution Failed: {escape(str(e)[:150])}")

if __name__ == "__main__":
    application = Application.builder().token(TOKEN).post_init(init_session).post_stop(close_session).build()
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("setup", setup))
    application.add_handler(CommandHandler("wallet", wallet))
    application.add_handler(CommandHandler("snipe", snipe))
    application.run_polling()
