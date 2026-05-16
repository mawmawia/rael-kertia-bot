import discord
from discord.ext import commands
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

# ENV VARS - Make sure these exist in Railway
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
BIRDEYE_KEY = os.getenv('BIRDEYE_API_KEY')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

async def scan_token_birdeye(chain: str, address: str) -> str:
    """
    Main scanner using Birdeye API (Asynchronous)
    """
    chain_map = {
        'eth': 'ethereum', 'ethereum': 'ethereum',
        'bsc': 'bsc', 'bnb': 'bsc',
        'base': 'base', 
        'arb': 'arbitrum', 'arbitrum': 'arbitrum',
        'sol': 'solana', 'solana': 'solana',
        'poly': 'polygon', 'polygon': 'polygon'
    }
    
    birdeye_chain = chain_map.get(chain.lower())
    if not birdeye_chain:
        return f"❌ Unsupported chain: `{chain}`. Use: eth, bsc, base, arb, sol"
    
    url = f"https://public-api.birdeye.so/defi/token_overview?address={address}"
    headers = {
        "X-API-KEY": BIRDEYE_KEY, 
        "x-chain": birdeye_chain
    }
    
    # Use aiohttp ClientSession with a 5-second total timeout
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as r:
                
                if r.status == 401:
                    return "❌ Birdeye API key invalid. Check Railway Variables."
                if r.status == 429:
                    return "❌ Rate limited. Wait 60s or upgrade Birdeye plan."
                if r.status != 200:
                    return "❌ Token not found. Check chain/address."
                
                response_json = await r.json()
                data = response_json.get('data', {})
                
                if not data:
                    return "❌ Token not found or no data returned."
                
                # Parse Birdeye response with fallback values
                name = data.get('name', 'Unknown')
                symbol = data.get('symbol', '?')
                mc = data.get('mc', 0) or 0
                liquidity = data.get('liquidity', 0) or 0
                holder = data.get('holder', 0) or 0
                lp_locked = data.get('lpLockedPct', 0) or 0
                price = data.get('price', 0) or 0
                v24h = data.get('v24hUSD', 0) or 0
                
                # Risk flags
                risk_flags = []
                if liquidity < 10000:
                    risk_flags.append("⚠️ Low LP < $10k")
                if lp_locked < 50:
                    risk_flags.append(f"⚠️ LP only {lp_locked:.1f}% locked")
                if holder < 50:
                    risk_flags.append("⚠️ Holders < 50")
                    
                risk_text = "\n".join(risk_flags) if risk_flags else "✅ No major red flags"
                hidden_tax = "Run scan again for deep tax check"
                
                return f"""
🛡️ **Kertia Scan** 

**{name} (${symbol})** | `{birdeye_chain}`
💵 Price: ${price:.8f}
💰 MC: ${mc:,.0f}
📊 24h Vol: ${v24h:,.0f}
💧 LP: ${liquidity:,.0f} | {lp_locked:.1f}% Locked
👥 Holders: {holder:,}

**Risk Check:**
{risk_text}

**Hidden Tax:**
🔍 {hidden_tax}

⚡ Powered by Birdeye
"""
        
    except aiohttp.ClientConnectorError:
        return "❌ Connection error. Cannot reach Birdeye."
    except Exception as e:
        return f"❌ Scan error: {str(e)[:100]}"

@bot.event
async def on_ready():
    print(f'Kertia online as {bot.user}')
    print(f'Birdeye key loaded: {bool(BIRDEYE_KEY)}')

@bot.command(name='scan')
async def scan(ctx, chain: str = None, address: str = None):
    """Scan any token: /scan eth 0x..."""
    if not chain or not address:
        await ctx.send("**Usage:** `/scan <chain> <address>`\n**Example:** `/scan eth 0x4ed4e862860bed51a99a7b96cf246c67a12d5e3d`\n**Chains:** eth, bsc, base, arb, sol")
        return
    
    msg = await ctx.send("🔍 Scanning...")
    
    # We now await the async function
    result = await scan_token_birdeye(chain, address)
    
    await msg.edit(content=result)

@bot.command(name='ping')
async def ping(ctx):
    """Test if bot is alive"""
    await ctx.send("Kertia online ⚡")

# Run bot
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in env")
    elif not BIRDEYE_KEY:
        print("ERROR: BIRDEYE_API_KEY not set in env")
    else:
        bot.run(DISCORD_TOKEN)
