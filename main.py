import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from web3 import Web3
from eth_account import Account
from cryptography.fernet import Fernet
from users import init_db, close_db, get_user, save_user # NEW

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true" # Default True for safety

WETH_ADDRESS_CORRECT = "0x4200000000000000000000000006"
UNISWAP_V2_ROUTER = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
FEE_RECIPIENT = os.getenv("FEE_RECIPIENT", "0xYourFeeWalletHere")

TOTAL_FEE_BPS = 50
REF_BONUS_BPS = 10

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
cipher_suite = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

# --- UTILS ---
def encrypt_pk(pk: str) -> str:
    return cipher_suite.encrypt(pk.encode()).decode()

def decrypt_pk(encrypted_pk: str) -> str:
    return cipher_suite.decrypt(encrypted_pk.encode()).decode()

def is_valid_address(address: str) -> bool:
    return w3.is_address(address)

def to_checksum(address: str) -> str:
    return w3.to_checksum_address(address)

async def check_goplus(token_address: str) -> Dict:
    url = f"https://api.gopluslabs.io/api/v1/token_security/8453?contract_addresses={token_address}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                data = await resp.json()
                return data.get('result', {}).get(token_address.lower(), {})
    except Exception as e:
        logger.error(f"GoPlus error: {e}")
        return {}

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = await get_user(user_id) # Postgres fetch

    if not user_data:
        user_data = {
            "wallet": None,
            "ref_by": context.args[0] if context.args else None,
            "created": datetime.utcnow().isoformat(),
            "total_volume": 0,
            "total_fees_paid": 0
        }
        await save_user(user_id, user_data) # Atomic upsert
        await update.message.reply_text(
            "⚔️ Welcome to Rael_Kertia Engine v3.2\n\n"
            "0.5% fees. Anti-MEV. Honeypot shield.\n"
            "Use /setup_wallet to begin.\n\n"
            f"Your ref: `{user_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("Welcome back. Use /help for commands.")

async def setup_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = await get_user(user_id)

    if user_data.get("wallet"):
        await update.message.reply_text("Wallet already exists. Use /wallet to view.")
        return

    acct = Account.create()
    encrypted_pk = encrypt_pk(acct.key.hex())

    user_data["wallet"] = {
        "address": acct.address,
        "pk_encrypted": encrypted_pk
    }
    await save_user(user_id, user_data)

    await update.message.reply_text(
        f"✅ Wallet created\n"
        f"Address: `{acct.address}`\n\n"
        f"⚠️ BACKUP YOUR PRIVATE KEY NOW:\n"
        f"`{acct.key.hex()}`\n\n"
        f"Fund this wallet with Base ETH to snipe.",
        parse_mode=ParseMode.MARKDOWN
    )

#... keep scan, ping, help same as before, but update any load_users calls...

async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = await get_user(user_id) # Postgres fetch

    if not context.args or len(context.args) < 3:
        await update.message.reply_text("Usage: /snipe base <token> <eth_amount>")
        return

    token = context.args[1].strip()
    try:
        eth_amount = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Invalid ETH amount")
        return

    if not is_valid_address(token):
        await update.message.reply_text("❌ Invalid token address")
        return

    token = to_checksum(token)
    if not user_data or not user_data.get("wallet"):
        await update.message.reply_text("❌ Run /setup_wallet first")
        return

    msg = await update.message.reply_text("⚡ Building transaction...")

    goplus_data = await check_goplus(token)
    if goplus_data.get('is_honeypot') == '1':
        await msg.edit_text("🚨 Honeypot detected. Snipe cancelled to protect funds.")
        return

    wallet_addr = user_data["wallet"]["address"]
    pk = decrypt_pk(user_data["wallet"]["pk_encrypted"])
    acct = Account.from_key(pk)

    eth_wei = w3.to_wei(eth_amount, 'ether')
    total_fee = int(eth_wei * TOTAL_FEE_BPS / 10000)
    swap_amount = eth_wei - total_fee

    router = w3.eth.contract(address=to_checksum(UNISWAP_V2_ROUTER), abi=[{"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"payable","type":"function"}])

    path = [to_checksum(WETH_ADDRESS_CORRECT), token]
    deadline = int((datetime.utcnow() + timedelta(minutes=20)).timestamp())

    swap_tx_params = {
        'from': wallet_addr,
        'value': swap_amount,
        'nonce': w3.eth.get_transaction_count(wallet_addr),
        'chainId': 8453
    }

    try:
        estimated_gas = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, path, wallet_addr, deadline
        ).estimate_gas(swap_tx_params)
        swap_tx_params['gas'] = int(estimated_gas * 1.2)
    except Exception as e:
        logger.error(f"Gas estimate failed for {token}: {e}")
        await msg.edit_text("❌ Cannot estimate gas. Snipe aborted to save your ETH.")
        return

    if DRY_RUN:
        await msg.edit_text(
            f"🚀 [DRY_RUN] Ready\n"
            f"Amount: {w3.from_wei(swap_amount, 'ether'):.6f} ETH\n"
            f"Fee: {w3.from_wei(total_fee, 'ether'):.6f} ETH\n"
            f"Gas: {swap_tx_params['gas']}"
        )
        return

    try:
        swap_tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, path, wallet_addr, deadline
        ).build_transaction(swap_tx_params)

        signed = acct.sign_transaction(swap_tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)

        fee_tx = {
            'to': to_checksum(FEE_RECIPIENT),
            'value': total_fee,
            'gas': 21000,
            'gasPrice': w3.eth.gas_price,
            'nonce': swap_tx_params['nonce'] + 1,
            'chainId': 8453
        }
        signed_fee = acct.sign_transaction(fee_tx)
        w3.eth.send_raw_transaction(signed_fee.rawTransaction)

        # Update stats
        user_data["total_volume"] = user_data.get("total_volume", 0) + eth_amount
        user_data["total_fees_paid"] = user_data.get("total_fees_paid", 0) + w3.from_wei(total_fee, 'ether')
        await save_user(user_id, user_data)

        await msg.edit_text(
            f"✅ Snipe sent!\n"
            f"TX: `https://basescan.org/tx/{tx_hash.hex()}`\n"
            f"Fee paid: {w3.from_wei(total_fee, 'ether'):.6f} ETH",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Snipe execution failed: {e}")
        await msg.edit_text(f"❌ Transaction failed: {str(e)[:100]}")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = await get_user(user_id)
    wallet_data = user_data.get("wallet")

    if not wallet_data:
        await update.message.reply_text("No wallet. Run /setup_wallet")
        return

    addr = wallet_data["address"]
    bal = w3.eth.get_balance(addr)
    await update.message.reply_text(
        f"💼 Your Wallet\n"
        f"Address: `{addr}`\n"
        f"Balance: {w3.from_wei(bal, 'ether'):.6f} ETH",
        parse_mode=ParseMode.MARKDOWN
    )

#... keep ping, scan, help same but ensure all use get_user/save_user...

async def on_startup(app: Application):
    await init_db()

async def on_shutdown(app: Application):
    await close_db()

def main():
    if not BOT_TOKEN or not ENCRYPTION_KEY:
        raise ValueError("BOT_TOKEN and ENCRYPTION_KEY env vars required")

    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).post_shutdown(on_shutdown).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("setup_wallet", setup_wallet))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("snipe", snipe))
    app.add_handler(CommandHandler("wallet", wallet))

    logger.info(f"Rael_Kertia Engine v3.2 Online | DRY_RUN={DRY_RUN}")
    app.run_polling()

if __name__ == "__main__":
    main()
