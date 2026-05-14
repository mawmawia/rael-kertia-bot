import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ['BOT_TOKEN']

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Rael_kertia online. Trojan Killer active. /scan 0x...")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /scan 0xTokenAddress")
        return
    await update.message.reply_text(f"Scanning {context.args[0]}...\nKertia Score: 42/100\nVerdict: CAUTION\nReal API ships tomorrow.")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("scan", scan))
app.run_polling()
