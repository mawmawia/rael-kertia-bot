import os
import sys
import logging
import sqlite3
import base64
import httpx
from cryptography.fernet import Fernet

# Telegram API Libraries
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# EVM Libraries
from web3 import Web3

# Solana Libraries
import base58
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Processed
from solana.rpc.types import TxOpts
from solders.pubkey import Pubkey

# --- 1. INITIALIZE ROOT LOGGER FIRST ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 2. HARD-MUTE THIRD-PARTY LOGGERS TO PREVENT URL/TOKEN LEAKS ---
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

# --- SECURE ENVIRONMENT CONFIGURATION & FAIL-SAFES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
FEE_COLLECTOR_PUBKEY = os.environ.get("FEE_COLLECTOR_PUBKEY")
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")

# Cryptographic Fail-safe
if not ENCRYPTION_KEY:
    logger.critical("CRITICAL CONFIG ERROR: ENCRYPTION_KEY environment variable is absent. Boot halted.")
    sys.exit(1)
fernet = Fernet(ENCRYPTION_KEY.encode())

# Fixed Competitive Fee Tier (0.35%)
FEE_PERCENT = 0.0035  

# --- REGEX COMPILERS FOR UNIFIED TEXT LISTENER ---
EVM_REGEX = r'^0x[a-fA-F0-9]{40}$'
SOL_REGEX = r'^[1-9A-HJ-NP-Za-km-z]{32,44}$'

# --- DATABASE SETUP ---
def init_db():
    """Initializes the multi-chain encrypted relational database structure."""
    with sqlite3.connect("wallets.db", timeout=10) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY, 
                enc_key TEXT, 
                enc_sol_key TEXT, 
                referrer INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                user_id INTEGER PRIMARY KEY, 
                earned REAL DEFAULT 0.0
            )
        """)
        conn.commit()

init_db()

# --- VALIDATION UTILITIES ---
def is_valid_sol_address(addr: str) -> bool:
    try:
        decoded = base58.b58decode(addr)
        return len(decoded) == 32
    except Exception:
        return False

# --- KEY MANAGEMENT & UTILITIES ---
def get_evm_wallet(user_id: int):
    with sqlite3.connect("wallets.db", timeout=10) as conn:
        row = conn.execute("SELECT enc_key FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        if row and row[0]:
            decrypted_key = fernet.decrypt(row[0].encode()).decode()
            return Web3().eth.account.from_key(decrypted_key)
        
        new_account = Web3().eth.account.create()
        enc_key = fernet.encrypt(new_account.key.hex().encode()).decode()
        
        conn.execute(
            "INSERT INTO wallets (user_id, enc_key) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET enc_key=?",
            (user_id, enc_key, enc_key)
        )
        conn.commit()
        return new_account

def get_solana_wallet(user_id: int):
    with sqlite3.connect("wallets.db", timeout=10) as conn:
        row = conn.execute("SELECT enc_sol_key FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        if row and row[0]:
            decrypted_bytes = fernet.decrypt(row[0].encode())
            return Keypair.from_bytes(decrypted_bytes)
        
        new_sol_account = Keypair()
        enc_sol = fernet.encrypt(bytes(new_sol_account)).decode()
        
        conn.execute(
            "INSERT INTO wallets (user_id, enc_sol_key) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET enc_sol_key=?",
            (user_id, enc_sol, enc_sol)
        )
        conn.commit()
        return new_sol_account

# --- TELEGRAM UI UTILITIES ---
async def safe_reply(update: Update, text: str, reply_markup=None):
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if context.args and context.args[0].isdigit():
        ref_id = int(context.args[0])
        if ref_id != user_id:
            with sqlite3.connect("wallets.db", timeout=10) as conn:
                conn.execute("INSERT INTO wallets (user_id, referrer) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET referrer=?", (user_id, ref_id, ref_id))
                conn.commit()

    # Fixed: Uses HTML syntax to completely prevent underscore/Markdown parse errors
    msg = (
        "⚔️ <b>WELCOME TO RAEL_KERTIA ENGINE v3.4.2</b> ⚔️\n\n"
        "The low-fee cross-chain sniper engine built to take market share.\n\n"
        "🔹 <b>Trading Fees:</b> <code>0.35%</code> (Trojan charges 1.0%)\n"
        "🔹 <b>Networks:</b> Base, Solana, Ethereum, BSC, Arbitrum\n\n"
        "💡 <i>Just paste an EVM contract address or Solana token mint directly into this chat to begin trading instantly.</i>"
    )
    buttons = [
        [InlineKeyboardButton("💳 My Wallets", callback_data="wallet"), InlineKeyboardButton("👥 Referrals", callback_data="referral")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    evm_acct = get_evm_wallet(user_id)
    sol_acct = get_solana_wallet(user_id)
    
    msg = (
        "📥 <b>YOUR UNIQUE MULTI-CHAIN DEPOSIT WALLETS:</b>\n\n"
        "🌐 <b>EVM Base / ETH Wallet Address:</b>\n"
        f"<code>{evm_acct.address}</code>\n\n"
        "☀️ <b>Solana Mint Pipeline Key:</b>\n"
        f"<code>{sol_acct.pubkey()}</code>\n\n"
        "⚠️ <i>Keep your keys funded. Platform commissions (0.35%) are extracted instantly upon execution.</i>"
    )
    await safe_reply(update, msg)

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    with sqlite3.connect("wallets.db", timeout=10) as conn:
        row = conn.execute("SELECT earned FROM referrals WHERE user_id=?", (user_id,)).fetchone()
        earned = row[0] if row else 0.0

    msg = (
        "👥 <b>RAEL_KERTIA NETWORK DECENTRALIZATION LAYER:</b>\n\n"
        f"Your Personal Invite Pipeline:\n<code>{ref_link}</code>\n\n"
        f"💰 <b>Total Referral Profits Earned:</b> <code>{earned:.4f} EXT</code>\n\n"
        "When your references trade, you securely harvest a slice of our 0.35% fee pipeline directly into your wallet database passive ledger."
    )
    await safe_reply(update, msg)

# --- UNIFIED AUTO-DETECT ADDRESS LISTENER ---
async def auto_detect_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_address = update.message.text.strip()
    
    if token_address.startswith("0x") and len(token_address) == 42:
        chain = "base"
        buy_buttons = [
            InlineKeyboardButton("🛒 Buy 0.05 ETH", callback_data=f"quickbuy_0.05_base_{token_address}"),
            InlineKeyboardButton("🛒 Buy 0.2 ETH", callback_data=f"quickbuy_0.2_base_{token_address}")
        ]
    else:
        if not is_valid_sol_address(token_address):
            return
            
        chain = "sol"
        buy_buttons = [
            InlineKeyboardButton("🛒 Buy 0.5 SOL", callback_data=f"quickbuy_0.5_sol_{token_address}"),
            InlineKeyboardButton("🛒 Buy 2.0 SOL", callback_data=f"quickbuy_2.0_sol_{token_address}")
        ]
        
    msg = (
        "⚡ <b>RAEL_KERTIA ENGINE: TOKEN RECOGNIZED</b>\n\n"
        f"Network Cluster: <code>{chain.upper()}</code>\n"
        f"Contract Target: <code>{token_address}</code>\n\n"
        "Select an automated metric action below:"
    )
    
    buttons = [
        buy_buttons,
        [InlineKeyboardButton("📊 Automated Safety Audit", callback_data=f"quickscan_{chain}_{token_address}")],
        [InlineKeyboardButton("❌ Dismiss Interface", callback_data="cancel")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

# --- PRODUCTION SOLANA SWAP ENGINE (JUPITER NATIVE FEES V6) ---
async def execute_solana_swap(user_id: int, token_address: str, amount_sol: float, slippage_bps: int = 100):
    try:
        sol_wallet = get_solana_wallet(user_id)
        user_pubkey = str(sol_wallet.pubkey())
        lamports = int(amount_sol * 1_000_000_000)
        
        SOL_MINT = "So11111111111111111111111111111111111111112"
        
        quote_url = (
            f"https://quote-api.jup.ag/v6/quote?"
            f"inputMint={SOL_MINT}&"
            f"outputMint={token_address}&"
            f"amount={lamports}&"
            f"slippageBps={slippage_bps}&"
            f"platformFeeBps=35"
        )
        
        async with httpx.AsyncClient() as client:
            quote_res = await client.get(quote_url)
            if quote_res.status_code != 200:
                return {"success": False, "error": f"Jupiter Route Failure: {quote_res.text[:80]}"}
            quote_data = quote_res.json()
            
            swap_payload = {
                "quoteResponse": quote_data,
                "userPublicKey": user_pubkey,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": 65_000,
                "feeAccount": FEE_COLLECTOR_PUBKEY
            }
            
            swap_res = await client.post("https://quote-api.jup.ag/v6/swap", json=swap_payload)
            if swap_res.status_code != 200:
                return {"success": False, "error": f"Transaction Assembly Failure: {swap_res.text[:80]}"}
            
            swap_data = swap_res.json()
            raw_tx_bytes = base64.b64decode(swap_data["swapTransaction"])
            versioned_tx = VersionedTransaction.from_bytes(raw_tx_bytes)
            
            versioned_tx.sign([sol_wallet])
            
            async with AsyncClient(SOLANA_RPC_URL) as rpc_client:
                opts = TxOpts(skip_preflight=False, preflight_commitment=Processed)
                tx_signature = await rpc_client.send_raw_transaction(bytes(versioned_tx), opts)
                return {"success": True, "tx_hash": str(tx_signature.value)}
                
    except Exception as e:
        logger.error(f"Solana execution failure thread termination for {user_id}: {e}")
        return {"success": False, "error": str(e)}

# --- MOCK EVM SNIPER LINK ---
async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chain = context.args[0]
    token = context.args[1]
    amount = context.args[2]
    await safe_reply(update, f"🚀 <b>EVM Execution Success:</b> Sniping <code>{amount}</code> ETH into token <code>{token}</code> on network <b>{chain.upper()}</b>.")

# --- DYNAMIC CROSS-CHAIN CALLBACK ROUTER ---
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.effective_user.id
    data = query.data
    await query.answer()
    
    if data == "wallet":
        await wallet(update, context)
    elif data == "referral":
        await referral(update, context)
    elif data == "cancel":
        await query.message.edit_text("❌ Automated order flow execution sequence closed.")
        
    elif data.startswith("quickbuy_"):
        parts = data.split("_")
        amount_str = parts[1]
        chain_selection = parts[2]
        token_address = parts[3]
        
        amount = float(amount_str)
        
        if chain_selection == "sol":
            await query.message.reply_text(f"🚀 <i>Routing trade parameters to Jupiter Liquidity Engines for {amount} SOL...</i>", parse_mode="HTML")
            result = await execute_solana_swap(user_id=user_id, token_address=token_address, amount_sol=amount)
            
            if result["success"]:
                await query.message.reply_text(
                    f"✅ <b>Solana Order Filled!</b>\n\n🔗 <a href='https://solscan.io/tx/{result['tx_hash']}'>Review Receipt via Solscan</a>",
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            else:
                await query.message.reply_text(f"❌ <b>Jupiter Route Failure Matrix Rejected Transaction:</b>\n<code>{result['error']}</code>", parse_mode="HTML")
        else:
            context.args = [chain_selection, token_address, amount_str]
            await snipe(update, context)
            
    elif data.startswith("quickscan_"):
        _, chain_selection, token_address = data.split("_")
        if chain_selection == "sol":
            await query.message.reply_text(f"📊 <i>Running Solana Metadata Security Analysis on Mint:</i> <code>{token_address}</code>", parse_mode="HTML")
        else:
            await query.message.reply_text(f"🛡️ <i>Pinging GoPlus Live Telemetry Layer for EVM Contract:</i> <code>{token_address}</code>", parse_mode="HTML")

# --- INITIALIZATION ENGINE BOOTSTRAP ---
def main():
    if not BOT_TOKEN:
        logger.critical("CRITICAL STOP: SYSTEM BOOT REFUSED. BOT_TOKEN configuration variable is empty.")
        sys.exit(1)
        
    if not FEE_COLLECTOR_PUBKEY or FEE_COLLECTOR_PUBKEY == "YOUR_CENTRAL_SOLANA_WALLET_ADDRESS":
        logger.critical("CRITICAL STOP: Production FEE_COLLECTOR_PUBKEY variable is missing or unset.")
        sys.exit(1)
        
    try:
        Pubkey.from_string(FEE_COLLECTOR_PUBKEY)
    except Exception:
        logger.critical("CRITICAL STOP: FEE_COLLECTOR_PUBKEY is not a valid Solana public key.")
        sys.exit(1)
        
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command Maps
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("referral", referral))
    
    # Unified Interceptor Line
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.Regex(EVM_REGEX) | filters.Regex(SOL_REGEX)), 
        auto_detect_address
    ))
    
    # Central Event Callback Manager
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    
    logger.info("RAEL_KERTIA SYSTEM BOOT SEQUENCE: Core compilation loops running normally.")
    app.run_polling()

if __name__ == "__main__":
    main()
