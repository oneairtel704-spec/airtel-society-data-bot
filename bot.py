import os
import psycopg2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import nest_asyncio
import time
import re
nest_asyncio.apply()

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")

authenticated_agents = {}
SESSION_DURATION = 12*60*60


def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def verify_olm_id(olm_id):
    if not re.matc(r'^A\d{7}$', olm_id):
        return None
    conn = get_db_connection()
    cursor = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM agents WHERE OLM_ID = %s", (olm_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else None

def is_authenticated(user_id):
    if user_id not in authenticated_agents:
        return False
    session = authenticated_agents[user_id]
    if time.time() - session["timestamp"] > SESSION_DURATION:
        del authenticated_agents[user_id]
        return False
    return True       
        


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
    user_id = update.message.from_user.id 
    if is_authenticated(user_id):
       name = authenticated_agents[user_id]["name"]
       await update.message.reply_text(
        "Welcome back" + name +  "!\n\n"
        "To search, type:\n"
        "RSU CODE followed by BUILDING NAME\n\n"
        "Example: MWE Sneha Sadan"
        "Type /help for more info."
       )
    else:
        await update.message.reply_text(
            "Welcome to the Airtel Society Data Bot \n\n"
            "Please enter your OLM ID to continue.\n\n"
            "Example: A1234567"
        )   

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Airtel Society Data Bot - Help\n\n"
        "HOW TO SEARCH:\n"
        "Type your RSU code followed by the building name\n\n"
        "EXAMPLE:\n"
        "MWE Sneha Sadan\n\n"
        "WHAT YOU GET:\n"
        "- Total flats in the building\n"
        "- Airtel postpaid users\n"
        "- Airtel prepaid users\n"
        "- Airtel WiFi users\n"
        "- One Airtel Plan (OAP) users\n"
        "- Opportunity (flats not yet on Airtel postpaid)\n\n"
        "TIPS:\n"
        "- You can type part of the name e.g. MWE Sneha\n"
        "- RSU code must be correct\n"
        "- Contact your manager if your RSU code is unknown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Message received: " + update.message.text)
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    if not is_authenticated(user_id):
        olm_id = text.upper()
        name = verify_olm_id(olm_id)
        if name:
            authenticated_agents[user_id] = {
                "olm_id": olm_id,
                "name": name,
                "timestamp": time.time()
            }
            await.update.message.reply_text(
                "Welcome " + name + "! You are now logged in. \n\n"
                "To search, type:\n"
                "RSU CODE followed by BUILDING NAME\n\n"
                "Example: MWE Sneha Sadan"
            )
        else:
            await update.message.reply_text(
                "Invalid OLM ID. Please try again. \n\n"
                "Make sure your ID is in the format A1234567\n"
                "Contact your TM if you need help."
            )
        return

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
    await app.run_polling(drop_pending_updates=True)

asyncio.run(main())