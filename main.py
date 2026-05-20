import os
import logging
import asyncio
import sqlite3
import json
import base64
from typing import Optional
import aiohttp
from cryptography.fernet import Fernet

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
from web3 import Web3

# ============== CONFIG ==============
BOT_TOKEN = os.getenv("BOT_TOKEN")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
FEE_COLLECTOR_PUBKEY = os.getenv("FEE_COLLECTOR_PUBKEY")
SOLANA_RPC = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
EVM_RPC = os.getenv("EVM_RPC", "https://mainnet.infura.io/v3/YOUR_KEY")

FEE_BPS = 35 # 0.35%
DB_PATH = "wallets.db"
JUPITER_API = "https://quote-api.jup.ag/v6"
JUPITER_PRICE_API = "https://price.jup.ag/v4/price"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== ENCRYPTION ==============
fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt_key(key_str: str) -> str:
    return fernet.encrypt(key_str.encode()).decode()

def decrypt_key(enc_str: str) -> str:
    return fernet.decrypt(enc_str.encode()).decode()

# ============== DATABASE ==============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS wallets
                 (user_id INTEGER PRIMARY KEY, 
                  sol_key TEXT, 
                  evm_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  chain TEXT,
                  token_in TEXT,
                  token_out TEXT,
                  amount_in TEXT,
                  entry_price REAL,
                  stop_loss REAL,
                  take_profit REAL,
                  status TEXT DEFAULT 'open')''')
    conn.commit()
    conn.close()

def get_wallet(user_id: int) -> Optional:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT sol_key, evm_key FROM wallets WHERE user_id =?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"sol": decrypt_key(row[0]) if row[0] else None, "evm": decrypt_key(row[1]) if row[1] else None}
    return None

def save_wallet(user_id: int, sol_key: str = None, evm_key: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_wallet(user_id)
    sol_enc = encrypt_key(sol_key) if sol_key else (encrypt_key(existing["sol"]) if existing and existing["sol"] else None)
    evm_enc = encrypt_key(evm_key) if evm_key else (encrypt_key(existing["evm"]) if existing and existing["evm"] else None)
    c.execute("INSERT OR REPLACE INTO wallets (user_id, sol_key, evm_key) VALUES (?,?,?)", 
              (user_id, sol_enc, evm_enc))
    conn.commit()
    conn.close()

def add_position(user_id: int, chain: str, token_in: str, token_out: str, amount_in: str, entry_price: float, sl: float, tp: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO positions (user_id, chain, token_in, token_out, amount_in, entry_price, stop_loss, take_profit) 
                 VALUES (?,?,?,?,?,?,?,?)""",
              (user_id, chain, token_in, token_out, amount_in, entry_price, sl, tp))
    conn.commit()
    conn.close()

def get_open_positions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM positions WHERE status = 'open'")
    rows = c.fetchall()
    conn.close()
    return rows

def close_position(pos_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE positions SET status = 'closed' WHERE id =?", (pos_id,))
    conn.commit()
    conn.close()

# ============== SOLANA HELPERS ==============
async def get_sol_price(mint: str) -> Optional[float]:
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{JUPITER_PRICE_API}?ids={mint}") as resp:
                data = await resp.json()
                return data['data'][mint]['price']
        except:
            return None

async def jupiter_swap(sol_key: str, input_mint: str, output_mint: str, amount: int, slippage: int = 100):
    kp = Keypair.from_base58_string(sol_key)
    async with aiohttp.ClientSession() as session:
        quote_params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": slippage,
            "platformFeeBps": FEE_BPS
        }
        if FEE_COLLECTOR_PUBKEY:
            try:
                fee_account = str(Pubkey.find_program_address(
                    [bytes(Pubkey.from_string(FEE_COLLECTOR_PUBKEY)), bytes(Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")), bytes(Pubkey.from_string(input_mint))],
                    Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
                )[0])
                quote_params["feeAccount"] = fee_account
            except:
                pass
        
        async with session.get(f"{JUPITER_API}/quote", params=quote_params) as resp:
            quote = await resp.json()
        
        swap_req = {
            "quoteResponse": quote,
            "userPublicKey": str(kp.pubkey()),
            "wrapAndUnwrapSol": True
        }
        async with session.post(f"{JUPITER_API}/swap", json=swap_req) as resp:
            swap_data = await resp.json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(swap_data['swapTransaction']))
        tx.sign([kp])
        client = AsyncClient(SOLANA_RPC)
        sig = await client.send_raw_transaction(bytes(tx))
        await client.close()
        return sig.value

# ============== BOT COMMANDS ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = get_wallet(user_id)
    
    if not wallet or not wallet["sol"]:
        kp = Keypair()
        save_wallet(user_id, sol_key=base64.b64encode(bytes(kp)).decode())
        msg = f"🔥 RAEL_KERTIA v3.7.1 Online\n\nNew Solana wallet created:\n{kp.pubkey()}\n\nFund it with SOL to trade. Use /wallet to see addresses.\nUse /buy <mint> <sol_amount> <sl%> <tp%>"
        await update.message.reply_text(msg)
    else:
        kp = Keypair.from_base58_string(wallet["sol"])
        msg = f"🔥 RAEL_KERTIA v3.7.1\n\nWallet: {kp.pubkey()}\n\nCommands:\n/buy <mint> <sol> <sl%> <tp%>\n/wallet\n/positions"
        await update.message.reply_text(msg)

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = get_wallet(user_id)
    if not wallet:
        await update.message.reply_text("No wallet. Use /start first.")
        return
    
    msg = "💼 Your Wallets\n\n"
    if wallet["sol"]:
        kp = Keypair.from_base58_string(wallet["sol"])
        msg += f"Solana: {kp.pubkey()}\n"
    if wallet["evm"]:
        w3 = Web3()
        acct = w3.eth.account.from_key(wallet["evm"])
        msg += f"EVM: {acct.address}\n"
    
    await update.message.reply_text(msg)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = get_wallet(user_id)
    if not wallet or not wallet["sol"]:
        await update.message.reply_text("No Solana wallet. Use /start first.")
        return
    
    try:
        mint = context.args[0]
        sol_amount = float(context.args[1])
        sl_pct = float(context.args[2])
        tp_pct = float(context.args[3])
    except:
        await update.message.reply_text("Usage: /buy <mint> <sol_amount> <sl%> <tp%>\nExample: /buy EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v 0.1 10 20")
        return
    
    await update.message.reply_text("🔄 Building swap...")
    
    try:
        lamports = int(sol_amount * 1e9)
        entry_price = await get_sol_price(mint)
        if not entry_price:
            await update.message.reply_text("❌ Could not fetch token price.")
            return
        
        sl_price = entry_price * (1 - sl_pct / 100)
        tp_price = entry_price * (1 + tp_pct / 100)
        
        sig = await jupiter_swap(
            wallet["sol"], 
            "So11111111111111111111111111111111111111112",
            mint, 
            lamports
        )
        
        add_position(user_id, "solana", "SOL", mint, str(lamports), entry_price, sl_price, tp_price)
        
        msg = f"✅ Buy executed\n\nToken: {mint}\nEntry: ${entry_price:.6f}\nSL: ${sl_price:.6f} (-{sl_pct}%)\nTP: ${tp_price:.6f} (+{tp_pct}%)\nTx: https://solscan.io/tx/{sig}\n\nMonitoring active."
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Buy error: {e}")
        await update.message.reply_text(f"❌ Swap failed: {str(e)}")

async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token_out, entry_price, stop_loss, take_profit FROM positions WHERE user_id =? AND status = 'open'", (user_id,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("No open positions.")
        return
    
    msg = "📊 Open Positions\n\n"
    for row in rows:
        msg += f"Token: {row[0]}\nEntry: ${row[1]:.6f}\nSL: ${row[2]:.6f}\nTP: ${row[3]:.6f}\n\n"
    await update.message.reply_text(msg)

# ============== SL/TP MONITOR ==============
async def monitor_loop(app: Application):
    await asyncio.sleep(5)
    logger.info("SL/TP Monitor starting...")
    while True:
        try:
            positions = get_open_positions()
            for pos in positions:
                pos_id, user_id, chain, token_in, token_out, amount_in, entry, sl, tp, status = pos
                if chain!= "solana":
                    continue
                
                current_price = await get_sol_price(token_out)
                if not current_price:
                    continue
                
                triggered = None
                if current_price <= sl:
                    triggered = "SL"
                elif current_price >= tp:
                    triggered = "TP"
                
                if triggered:
                    wallet = get_wallet(user_id)
                    if wallet and wallet["sol"]:
                        await app.bot.send_message(user_id, f"⚠️ {triggered} triggered for {token_out} at ${current_price:.6f}\nClosing position...")
                        try:
                            await jupiter_swap(
                                wallet["sol"],
                                token_out,
                                "So11111111111111111111111111111111111111112",
                                int(amount_in)
                            )
                            close_position(pos_id)
                            await app.bot.send_message(user_id, f"✅ Position closed via {triggered}")
                        except Exception as e:
                            await app.bot.send_message(user_id, f"❌ Failed to close: {e}")
                            if OWNER_ID:
                                await app.bot.send_message(OWNER_ID, f"Close failed for user {user_id}: {e}")
            
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Monitor loop error: {e}")
            if OWNER_ID:
                await app.bot.send_message(OWNER_ID, f"🚨 Monitor crashed: {e}")
            await asyncio.sleep(60)

# ============== MAIN ==============
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("positions", positions))
    
    asyncio.get_event_loop().create_task(monitor_loop(app))
    
    logger.info("RAEL_KERTIA v3.7.1 - SL/TP Monitor online")
    app.run_polling()

if __name__ == "__main__":
    main()
