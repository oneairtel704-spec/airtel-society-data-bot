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
        " airtel_postpaid_users, airtel_prepaid_users, airtel_wifi_users, airtel_oap_users"
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
    print("Message received: " + update.message.text)
    text = update.message.text.strip()
    parts = text.split(" ", 1)
    print("Parts: " + str(parts))

    if len(parts) < 2:
        await update.message.reply_text(
            "Please use the format:\n"
            "RSU CODE + BUILDING NAME\n\n"
            "Example: MWE Sneha Sadan"
        )
        return

    rsu = parts[0].upper()
    building_name = parts[1]
    print("Searching: " + rsu + " - " + building_name)
    results = search_buildings(rsu, building_name)
    print("Results: " + str(len(results)))

    if not results:
        print("No results found")
        await update.message.reply_text(
            "No buildings found for " + building_name + " in RSU " + rsu + ".\n\n"
            "Tips:\n"
            "Check your RSU code\n"
            "Try a shorter name\n"
            "Try just one word"
        )
        return

    print("Building row: " + str(results[0]))    
    if len(results) == 1:
          row = results[0]
          name = str(row[0])
          btype = str(row[1])
          loc = str(row[2])
          total = int(row[3]) if row[3] else 0
          postpaid = int(row[4]) if row[4] else 0
          prepaid = int(row[5]) if row[5] else 0
          wifi = int(row[6]) if row[6] else 0
          oap = int(row[7]) if row[7] else 0
          opportunity = total - postpaid

          def pct(val, tot):
            if val and tot:
              return str(val) + "/" + str(tot) + " (" + str(round(val*100/tot)) + "%)"
            return "N/A"

          lines = []
          lines.append("Building: " + name)
          lines.append("Type: " + btype)
          lines.append("Location: " + loc + " [" + rsu + "]")
          lines.append("")
          lines.append("Total Flats: " + str(total))
          lines.append("")
          lines.append("Airtel Penetration:")
          lines.append("Postpaid: " + pct(postpaid, total))
          lines.append("Prepaid: " + pct(prepaid, total))
          lines.append("WiFi: " + pct(wifi, total))
          lines.append("OAP: " + pct(oap, total))
          lines.append("")
          lines.append("Opportunity: " + str(opportunity) + " flats not yet on Airtel postpaid")
          msg = "\n".join(lines)
          print("Sending message now")
          await update.message.reply_text(msg)
          print("Done")
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