import os
import requests
from web3 import Web3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# --- ENV VARS ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEV_COLD_WALLET = os.getenv("DEV_COLD_WALLET")
BASE_RPC = os.getenv("BASE_RPC", "https://mainnet.base.org")
PRIVATE_KEY = os.getenv("BOT_WALLET_PRIVATE_KEY")
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY") # Optional but recommended

# --- SETTINGS ---
DRY_RUN = False # LIVE TRADING ON
FEE_PERCENT = 0.005 # 0.5%
CHAIN_ID = 8453 # Base
MIN_GAS_ETH = 0.0001 # ~₹21 - bot stops if below this

# --- WEB3 SETUP ---
w3 = Web3(Web3.HTTPProvider(BASE_RPC))
DEV_WALLET_CHECKSUM = Web3.to_checksum_address(DEV_COLD_WALLET)
bot_account = w3.eth.account.from_key(PRIVATE_KEY)
BOT_WALLET = bot_account.address

assert BOT_WALLET.lower() == "0x2cD33b0702A5046966C068250666ff7CF3F4ebBE".lower(), "Private key mismatch"

# --- HELPERS ---
def get_eth_price():
    """Get real ETH price from Birdeye. Fallback 2000 if fails."""
    if not BIRDEYE_KEY:
        return 2000
    try:
        url = "https://public-api.birdeye.so/defi/price?address=0x4200000000000000000000000006"
        headers = {"X-API-KEY": BIRDEYE_KEY}
        r = requests.get(url, headers=headers, timeout=5)
        return float(r.json()["data"]["value"])
    except:
        return 2000

def get_eth_balance(address):
    wei = w3.eth.get_balance(Web3.to_checksum_address(address))
    return float(w3.from_wei(wei, 'ether'))

def check_gas():
    balance = get_eth_balance(BOT_WALLET)
    return balance >= MIN_GAS_ETH, balance

async def send_dev_fee(amount_eth):
    """Sends 0.5% fee to cold wallet. Returns tx_hash or error."""
    gas_ok, bal = check_gas()
    if not gas_ok:
        return None, f"LOW GAS: {bal:.6f} ETH. Top up bot wallet."
    
    if DRY_RUN:
        return "0xDRYRUN", "Dry run mode"
    
    try:
        nonce = w3.eth.get_transaction_count(BOT_WALLET)
        tx = {
            'nonce': nonce,
            'to': DEV_WALLET_CHECKSUM,
            'value': w3.to_wei(amount_eth, 'ether'),
            'gas': 21000,
            'gasPrice': w3.eth.gas_price,
            'chainId': CHAIN_ID
        }
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        return w3.to_hex(tx_hash), None
    except Exception as e:
        return None, str(e)[:100]

def calculate_fee_split(amount_usd):
    eth_price = get_eth_price()
    fee_usd = amount_usd * FEE_PERCENT
    fee_eth = fee_usd / eth_price
    swap_usd = amount_usd - fee_usd
    return round(fee_usd, 4), round(fee_eth, 8), round(swap_usd, 4)

# --- TELEGRAM COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gas_ok, bal = check_gas()
    status = "✅ LIVE" if gas_ok else "⚠️ LOW GAS"
    await update.message.reply_text(
        f"**Rael_Kertia Bot v2.0 {status}**\n\n"
        f"Bot Wallet: `{BOT_WALLET[:6]}...{BOT_WALLET[-4:]}`\n"
        f"Fee Wallet: `{DEV_COLD_WALLET[:6]}...{DEV_COLD_WALLET[-4:]}`\n"
        f"Gas: `{bal:.6f} ETH`\n"
        f"Fee: {FEE_PERCENT*100}% per trade\n\n"
        f"Commands:\n/balance - Check wallets\n/testfee 100 - Test 0.5% on $100",
        parse_mode='Markdown'
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_eth = get_eth_balance(BOT_WALLET)
    cold_eth = get_eth_balance(DEV_COLD_WALLET)
    gas_ok, _ = check_gas()
    eth_price = get_eth_price()
    
    status = "✅ OK" if gas_ok else "⚠️ TOP UP NOW"
    
    await update.message.reply_text(
        f"**Wallet Status**\n\n"
        f"Bot Gas: `{bot_eth:.6f} ETH` = `${bot_eth*eth_price:.2f}` {status}\n"
        f"Cold Wallet: `{cold_eth:.6f} ETH` = `${cold_eth*eth_price:.2f}`\n"
        f"ETH Price: `${eth_price:.0f}`\n\n"
        f"Bot: `{BOT_WALLET}`\n"
        f"Cold: `{DEV_COLD_WALLET}`",
        parse_mode='Markdown'
    )

async def test_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(context.args[0])
        fee_usd, fee_eth, swap_usd = calculate_fee_split(amount)
        
        tx_hash, error = await send_dev_fee(fee_eth)
        
        if error:
            await update.message.reply_text(f"❌ Failed: {error}")
            return
            
        msg = f"**Test Trade ${amount}**\n\n"
        msg += f"User pays: `${amount}`\n"
        msg += f"Your fee: `${fee_usd}` = `{fee_eth} ETH`\n"
        msg += f"User swaps: `${swap_usd}`\n"
        msg += f"Fee Tx: `{tx_hash}`\n"
        if not DRY_RUN and tx_hash!= "0xDRYRUN":
            msg += f"View: https://basescan.org/tx/{tx_hash}\n"
        msg += f"Mode: {'DRY_RUN' if DRY_RUN else 'LIVE'}"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except IndexError:
        await update.message.reply_text("Usage: /testfee 100")
    except ValueError:
        await update.message.reply_text("Usage: /testfee 100 - must be a number")

def main():
    if not all([BOT_TOKEN, DEV_COLD_WALLET, PRIVATE_KEY]):
        raise ValueError("Missing TELEGRAM_TOKEN, DEV_COLD_WALLET, or BOT_WALLET_PRIVATE_KEY")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("testfee", test_fee))
    
    print(f"Bot LIVE. Gas wallet: {BOT_WALLET}. Fees to: {DEV_COLD_WALLET}")
    app.run_polling()

if __name__ == "__main__":
    main()
