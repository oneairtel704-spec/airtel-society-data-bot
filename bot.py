import os
import psycopg2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import nest_asyncio
nest_asyncio.apply()

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")


def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def search_buildings(rsu, building_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = (
        "SELECT building_name, building_type, locality, total_units,"
        " airtel_postpaid_users, airtel_wifi_users, airtel_oap_users"
        " FROM buildings"
        " WHERE rsu = %s"
        " AND building_name ILIKE %s"
        " LIMIT 5"
    )
    cursor.execute(query, (rsu.upper(), f"%{building_name}%"))
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Start command received")
    await update.message.reply_text(
        "Welcome to the Airtel Society Data Bot!\n\n"
        "To search, type:\n"
        "RSU CODE followed by BUILDING NAME\n\n"
        "Example: MWE Sneha Sadan"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(" ", 1)

    if len(parts) < 2:
        await update.message.reply_text(
            "Please use the format:\n"
            "RSU CODE + BUILDING NAME\n\n"
            "Example: MWE Sneha Sadan"
        )
        return

    rsu = parts[0].upper()
    building_name = parts[1]
    results = search_buildings(rsu, building_name)

    if not results:
        await update.message.reply_text(
            "No buildings found for " + building_name + " in RSU " + rsu + ".\n\n"
            "Tips:\n"
            "Check your RSU code\n"
            "Try a shorter name\n"
            "Try just one word"
        )
        return
    if len(results) == 1:
        row = results[0]
        total = row[3] if row[3] else 0
        postpaid = row[4] if row[4] else 0
        wifi = row[5] if row[5] else 0
        oap = row[6] if row[6] else 0
        opportunity = total - postpaid
        postpaid_pct = round((postpaid / total * 100)) if total > 0 else 0
        wifi_pct = round((wifi / total * 100)) if total > 0 else 0
        oap_pct = round((oap / total * 100)) if total > 0 else 0
        msg = (
            "Building: " + str(row[0]) + "\n"
            "Type: " + str(row[1]) + "\n"
            "Location: " + str(row[2]) + " [" + rsu + "]\n\n"
            "Total Flats: " + str(total) + "\n\n"
            "Airtel Penetration:\n"
            "Postpaid: " + str(postpaid) + "/" + str(total) + " (" + str(postpaid_pct) + "%)\n"
            "WiFi: " + str(wifi) + "/" + str(total) + " (" + str(wifi_pct) + "%)\n"
            "OAP: " + str(oap) + "/" + str(total) + " (" + str(oap_pct) + "%)\n\n"
            "Opportunity: " + str(opportunity) + " flats not yet on Airtel postpaid"
        )
        await update.message.reply_text(msg)
    else:
        response = "Found " + str(len(results)) + " matches in RSU " + rsu + ":\n\n"
        for i, row in enumerate(results, 1):
            response += str(i) + ". " + str(row[0]) + " - " + str(row[2]) + "\n"
        response += "\nDid you mean one of these? Try the exact name."
        await update.message.reply_text(response)


async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running...")
    await app.run_polling()

asyncio.run(main())