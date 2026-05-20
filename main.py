import os
import logging
import sqlite3
import asyncio
from cryptography.fernet import Fernet
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import aiohttp
import base58
import re
from web3 import Web3

# ============== CONFIG ==============
BOT_TOKEN = os.getenv("BOT_TOKEN")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
SOLANA_RPC = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
FEE_COLLECTOR_PUBKEY = os.getenv("FEE_COLLECTOR_PUBKEY")
PLATFORM_FEE_BPS = 35 # 0.35% platform fee
DB_PATH = "wallets.db"
EVM_RPC = os.getenv("EVM_RPC", "https://mainnet.base.org")
DEFAULT_SOL_AMOUNT = 0.01

# ============== LOGGING ==============
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ============== INIT ==============
if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY missing. Generate: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
fernet = Fernet(ENCRYPTION_KEY.encode())
sol_client = AsyncClient(SOLANA_RPC)
w3 = Web3(Web3.HTTPProvider(EVM_RPC))

# ============== DB SETUP ==============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER,
            chain TEXT,
            address TEXT,
            encrypted_key TEXT,
            PRIMARY KEY (user_id, chain)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            ref_code TEXT UNIQUE,
            referred_by INTEGER,
            earned INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdraws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chain TEXT,
            to_addr TEXT,
            amount TEXT,
            tx_sig TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY,
            sol_amount REAL DEFAULT 0.01
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ============== WALLET UTILS ==============
def create_sol_wallet():
    kp = Keypair()
    return str(kp.pubkey()), base58.b58encode(bytes(kp)).decode()

def create_evm_wallet():
    acct = w3.eth.account.create()
    return acct.address, acct.key.hex()

def encrypt_key(pk: str) -> str:
    return fernet.encrypt(pk.encode()).decode()

def decrypt_key(enc: str) -> str:
    return fernet.decrypt(enc.encode()).decode()

def save_wallet(user_id: int, chain: str, address: str, pk: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO wallets VALUES (?,?,?,?)", (user_id, chain, address, encrypt_key(pk)))
    conn.commit()
    conn.close()

def get_wallet(user_id: int, chain: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT address, encrypted_key FROM wallets WHERE user_id=? AND chain=?", (user_id, chain))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0], decrypt_key(row[1])
    return None, None

def log_withdraw(user_id: int, chain: str, to_addr: str, amount: str, tx_sig: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO withdraws (user_id, chain, to_addr, amount, tx_sig) VALUES (?,?,?,?,?)", 
                 (user_id, chain, to_addr, amount, tx_sig))
    conn.commit()
    conn.close()

def get_user_amount(user_id: int) -> float:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT sol_amount FROM settings WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else DEFAULT_SOL_AMOUNT

def set_user_amount(user_id: int, amount: float):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO settings (user_id, sol_amount) VALUES (?,?)", (user_id, amount))
    conn.commit()
    conn.close()

# ============== REFERRAL UTILS ==============
def get_or_create_ref(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT ref_code FROM referrals WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]
    ref_code = base58.b58encode(os.urandom(4)).decode()[:6]
    cur.execute("INSERT INTO referrals (user_id, ref_code) VALUES (?,?)", (user_id, ref_code))
    conn.commit()
    conn.close()
    return ref_code

def set_referrer(user_id: int, ref_code: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM referrals WHERE ref_code=?", (ref_code,))
    row = cur.fetchone()
    if row and row[0]!= user_id:
        cur.execute("UPDATE referrals SET referred_by=? WHERE user_id=? AND referred_by IS NULL", (row[0], user_id))
        conn.commit()
    conn.close()

# ============== JUPITER SWAP ==============
async def jupiter_swap(user_id: int, input_mint: str, output_mint: str, amount: int):
    addr, pk_str = get_wallet(user_id, "solana")
    if not addr:
        return None, "No Solana wallet. Use /start first."
    
    kp = Keypair.from_bytes(base58.b58decode(pk_str))
    
    async with aiohttp.ClientSession() as session:
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps=50&platformFeeBps={PLATFORM_FEE_BPS}"
        async with session.get(quote_url) as r:
            if r.status!= 200:
                return None, "Jupiter quote failed"
            quote = await r.json()
        
        swap_payload = {
            "quoteResponse": quote,
            "userPublicKey": addr,
            "wrapAndUnwrapSol": True,
            "feeAccount": FEE_COLLECTOR_PUBKEY
        }
        async with session.post("https://quote-api.jup.ag/v6/swap", json=swap_payload) as r:
            if r.status!= 200:
                txt = await r.text()
                return None, f"Jupiter swap build failed: {txt}"
            swap_data = await r.json()
        
        from base64 import b64decode
        from solders.transaction import VersionedTransaction
        raw_tx = b64decode(swap_data["swapTransaction"])
        tx = VersionedTransaction.from_bytes(raw_tx)
        tx.sign([kp])
        
        sig = await sol_client.send_raw_transaction(bytes(tx), opts=TxOpts(skip_preflight=True))
        return str(sig.value), None

# ============== WITHDRAW LOGIC ==============
async def withdraw_sol(user_id: int, to_addr: str, amount_sol: float):
    addr, pk_str = get_wallet(user_id, "solana")
    if not addr:
        return None, "No Solana wallet found"
    
    try:
        dest = Pubkey.from_string(to_addr)
    except:
        return None, "Invalid Solana address"
    
    kp = Keypair.from_bytes(base58.b58decode(pk_str))
    lamports = int(amount_sol * 1_000_000_000)
    
    bal = await sol_client.get_balance(kp.pubkey())
    if bal.value < lamports + 5000:
        return None, f"Insufficient balance. You have {bal.value/1e9:.6f} SOL"
    
    blockhash_resp = await sol_client.get_latest_blockhash()
    ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=dest, lamports=lamports))
    tx = Transaction.new_with_payer([ix], kp.pubkey())
    tx.sign([kp], blockhash_resp.value.blockhash)
    
    sig = await sol_client.send_raw_transaction(bytes(tx), opts=TxOpts(skip_preflight=True))
    log_withdraw(user_id, "SOL", to_addr, str(amount_sol), str(sig.value))
    return str(sig.value), None

def withdraw_evm(user_id: int, to_addr: str, amount_eth: float):
    addr, pk_hex = get_wallet(user_id, "evm")
    if not addr:
        return None, "No EVM wallet found"
    
    if not w3.is_address(to_addr):
        return None, "Invalid EVM address"
    
    wei_amount = w3.to_wei(amount_eth, 'ether')
    acct = w3.eth.account.from_key(pk_hex)
    
    bal = w3.eth.get_balance(acct.address)
    gas_price = w3.eth.gas_price
    gas_cost = 21000 * gas_price
    if bal < wei_amount + gas_cost:
        return None, f"Insufficient balance. Need {w3.from_wei(wei_amount + gas_cost, 'ether'):.6f} ETH for amount + gas"
    
    nonce = w3.eth.get_transaction_count(acct.address)
    tx = {
        'nonce': nonce,
        'to': to_addr,
        'value': wei_amount,
        'gas': 21000,
        'gasPrice': gas_price
    }
    
    signed_tx = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    log_withdraw(user_id, "EVM", to_addr, str(amount_eth), tx_hash.hex())
    return tx_hash.hex(), None

# ============== TELEGRAM HANDLERS ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if args and args[0].startswith("ref"):
        set_referrer(user_id, args[0][3:])
    
    if not get_wallet(user_id, "solana")[0]:
        addr, pk = create_sol_wallet()
        save_wallet(user_id, "solana", addr, pk)
    if not get_wallet(user_id, "evm")[0]:
        addr, pk = create_evm_wallet()
        save_wallet(user_id, "evm", addr, pk)
    
    ref_code = get_or_create_ref(user_id)
    user_amount = get_user_amount(user_id)
    
    text = f"""
<b>RAEL_KERTIA</b>

Instant SOL + EVM trading.
Ultra-low 0.35% platform fee.

<b>Current trade size: {user_amount} SOL</b>

Paste any token address to buy.
/setamount 0.5 - Change trade size
/withdraw SOL 0.1 <address>

Ref link: <code>https://t.me/{context.bot.username}?start=ref{ref_code}</code>
"""
    keyboard = [
        [InlineKeyboardButton("My Wallets", callback_data="wallets")],
        [InlineKeyboardButton("Referrals", callback_data="referrals")]
    ]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def set_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        current = get_user_amount(user_id)
        await update.message.reply_text(f"Usage: /setamount 0.5\nCurrent: {current} SOL")
        return
    
    try:
        amount = float(context.args[0])
        if amount <= 0 or amount > 1000:
            raise ValueError
    except:
        await update.message.reply_text("Invalid amount. Must be between 0 and 1000 SOL.")
        return
    
    set_user_amount(user_id, amount)
    await update.message.reply_text(f"✅ Trade size set to {amount} SOL")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "wallets":
        sol_addr, _ = get_wallet(user_id, "solana")
        evm_addr, _ = get_wallet(user_id, "evm")
        user_amount = get_user_amount(user_id)
        text = f"<b>Your Wallets</b>\n\n<b>SOL:</b> <code>{sol_addr}</code>\n<b>EVM:</b> <code>{evm_addr}</code>\n\n<b>Trade Size:</b> {user_amount} SOL\nUse /setamount to change"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    
    elif query.data == "referrals":
        ref_code = get_or_create_ref(user_id)
        text = f"<b>Referrals</b>\n\nEarn from your invites:\n<code>https://t.me/{context.bot.username}?start=ref{ref_code}</code>"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def withdraw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if len(args)!= 3:
        await update.message.reply_text("Usage: /withdraw SOL 0.1 <address> or /withdraw EVM 0.05 <address>")
        return
    
    chain, amount_str, to_addr = args[0].upper(), args[1], args[2]
    
    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("Invalid amount. Must be positive number.")
        return
    
    msg = await update.message.reply_text("Processing withdrawal...")
    
    if chain == "SOL":
        sig, err = await withdraw_sol(user_id, to_addr, amount)
        if err:
            await msg.edit_text(f"Failed: {err}")
        else:
            await msg.edit_text(f"Sent {amount} SOL\nTx: https://solscan.io/tx/{sig}")
    
    elif chain == "EVM":
        sig, err = withdraw_evm(user_id, to_addr, amount)
        if err:
            await msg.edit_text(f"Failed: {err}")
        else:
            await msg.edit_text(f"Sent {amount} ETH\nTx: https://basescan.org/tx/{sig}")
    else:
        await msg.edit_text("Chain must be SOL or EVM")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Solana token mint
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", text):
        amount_sol = get_user_amount(user_id)
        amount = int(amount_sol * 1_000_000_000)
        sol_mint = "So11111111111111112"
        
        msg = await update.message.reply_text(f"Executing {amount_sol} SOL swap...")
        sig, err = await jupiter_swap(user_id, sol_mint, text, amount)
        if err:
            await msg.edit_text(f"Error: {err}")
        else:
            await msg.edit_text(f"Swap confirmed: https://solscan.io/tx/{sig}")
        return
    
    # EVM address
    if w3.is_address(text):
        await update.message.reply_text("EVM trading module in development. You can withdraw with /withdraw EVM 0.1 <address>")
        return
    
    await update.message.reply_text("Send a token address to trade, or use /setamount /withdraw")

# ============== MAIN ==============
def main():
    if not BOT_TOKEN or not ENCRYPTION_KEY or not FEE_COLLECTOR_PUBKEY:
        raise ValueError("Missing env vars: BOT_TOKEN, ENCRYPTION_KEY, FEE_COLLECTOR_PUBKEY")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setamount", set_amount))
    app.add_handler(CommandHandler("withdraw", withdraw_cmd))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("RAEL_KERTIA v3.6.1 - Clean brand online")
    app.run_polling()

if __name__ == "__main__":
    main()
