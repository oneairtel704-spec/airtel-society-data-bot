import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from geopy.distance import geodesic
import pandas as pd
import re
import time
import os
import csv
from datetime import datetime
from io import StringIO
import requests

# ==========================================
# 1. CONFIG
# ==========================================

TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

SESSION_DURATION = 12 * 60 * 60  # 12 hours

GITHUB_RAW = "https://raw.githubusercontent.com/oneairtel704-spec/airtel-society-data-bot/main"
AGENTS_URL  = f"{GITHUB_RAW}/agents.csv"
SOCIETY_URL = f"{GITHUB_RAW}/buildings_society.csv"
RFS_URL     = f"{GITHUB_RAW}/buildings_rfs.csv"
ADMINS_URL  = f"{GITHUB_RAW}/admins.csv"
BANNED_URL  = f"{GITHUB_RAW}/banned_agents.csv"

# ==========================================
# 2. DATA LOADING
# ==========================================

def load_csv(url, label):
    try:
        df = pd.read_csv(url)
        print(f"✅ Loaded {len(df)} rows — {label}")
        return df
    except Exception as e:
        print(f"❌ Failed to load {label}: {e}")
        return pd.DataFrame()

df_agents  = load_csv(AGENTS_URL,  "agents.csv")
df_society = load_csv(SOCIETY_URL, "buildings_society.csv")
df_rfs     = load_csv(RFS_URL,     "buildings_rfs.csv")
df_admins  = load_csv(ADMINS_URL,  "admins.csv")
df_banned  = load_csv(BANNED_URL,  "banned_agents.csv")

# Agent lookup: olm_id -> name
AGENT_MAP = {}
if not df_agents.empty:
    for _, row in df_agents.iterrows():
        AGENT_MAP[str(row['olm_id']).strip().upper()] = str(row['name']).strip()
print(f"🔒 {len(AGENT_MAP)} agents loaded.")

# Admin set: telegram_ids who can use admin commands
ADMIN_IDS = set()
if not df_admins.empty and 'telegram_id' in df_admins.columns:
    ADMIN_IDS = set(df_admins['telegram_id'].astype(int).tolist())
print(f"👑 {len(ADMIN_IDS)} admins loaded.")

# Banned set: olm_ids that are banned
BANNED_OLM_IDS = set()
if not df_banned.empty and 'olm_id' in df_banned.columns:
    BANNED_OLM_IDS = set(df_banned['olm_id'].astype(str).str.strip().str.upper().tolist())
print(f"🚫 {len(BANNED_OLM_IDS)} banned agents loaded.")

# RFS buildings list
RFS_BUILDINGS = []
if not df_rfs.empty:
    df_rfs['Row_Index'] = range(len(df_rfs))
    RFS_BUILDINGS = df_rfs.to_dict('records')

# ==========================================
# 3. SESSION STATE
# ==========================================
# { user_id: { 'olm_id', 'name', 'timestamp', 'mode', 'rsu' } }
sessions = {}

def is_authenticated(user_id):
    if user_id not in sessions:
        return False
    if time.time() - sessions[user_id]['timestamp'] > SESSION_DURATION:
        del sessions[user_id]
        return False
    return True

def get_session(user_id):
    return sessions.get(user_id, {})

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ==========================================
# 4. HELPERS
# ==========================================

def validate_olm(olm_id):
    return bool(re.match(r'^A\d{7}$', olm_id))

def get_main_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🏘 Building Info", callback_data="mode_society"),
        InlineKeyboardButton("📡 Area RFS Info",  callback_data="mode_rfs")
    )
    return markup

def log_usage(user_id, name, action, search_data, output_summary):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = "usage_logs.csv"
    file_exists = os.path.exists(log_file) and os.path.getsize(log_file) > 0
    with open(log_file, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "User_ID", "Name", "Action", "Search_Data", "Output_Summary"])
        writer.writerow([timestamp, user_id, name, action, search_data, output_summary])

def save_report(user_id, agent_name, olm_id, building, mode, issue):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_file = "report_issue.csv"
    file_exists = os.path.exists(report_file) and os.path.getsize(report_file) > 0
    with open(report_file, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "User_ID", "Agent_Name", "OLM_ID", "Mode", "Building", "Issue"])
        writer.writerow([timestamp, user_id, agent_name, olm_id, mode, building, issue])
    log_usage(user_id, agent_name, "Report_Issue", building, "Saved")

def notify_admins(text, markup=None):
    for admin_id in ADMIN_IDS:
        try:
            if markup:
                bot.send_message(admin_id, text, parse_mode="Markdown", reply_markup=markup)
            else:
                bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception as e:
            print(f"❌ Could not notify admin {admin_id}: {e}")

def save_agent_to_csv(olm_id, name):
    """Append newly approved agent to agents.csv on server"""
    AGENT_MAP[olm_id.strip().upper()] = name.strip()
    log_file = "agents.csv"
    file_exists = os.path.exists(log_file) and os.path.getsize(log_file) > 0
    with open(log_file, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["olm_id", "name"])
        writer.writerow([olm_id, name])

def ban_agent(olm_id, telegram_id, name):
    """Add agent to banned list"""
    BANNED_OLM_IDS.add(olm_id.strip().upper())
    if olm_id.strip().upper() in AGENT_MAP:
        del AGENT_MAP[olm_id.strip().upper()]
    ban_file = "banned_agents.csv"
    file_exists = os.path.exists(ban_file) and os.path.getsize(ban_file) > 0
    with open(ban_file, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["olm_id", "telegram_id", "name"])
        writer.writerow([olm_id, telegram_id, name])

# ==========================================
# 5. ADMIN COMMANDS
# ==========================================

@bot.message_handler(commands=['users'])
def cmd_users(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Unauthorised.")
        return
    if not AGENT_MAP:
        bot.reply_to(message, "No authorised agents yet.")
        return
    response = "👥 *Authorised Agents:*\n\n"
    for olm, name in AGENT_MAP.items():
        response += f"• `{olm}` — {name}\n"
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=['revoke'])
def cmd_revoke(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Unauthorised.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Usage: `/revoke A1234567`", parse_mode="Markdown")
        return
    olm_id = parts[1].strip().upper()
    if olm_id not in AGENT_MAP:
        bot.reply_to(message, f"❌ OLM ID `{olm_id}` not found.", parse_mode="Markdown")
        return
    name = AGENT_MAP.get(olm_id, 'Unknown')
    ban_agent(olm_id, 0, name)
    # Kick active session if any
    for uid, sess in list(sessions.items()):
        if sess.get('olm_id') == olm_id:
            del sessions[uid]
            try:
                bot.send_message(uid, "⛔ *Your access has been revoked.*\n\nContact your TM for more information.", parse_mode="Markdown")
            except:
                pass
    bot.reply_to(message, f"✅ `{olm_id}` ({name}) has been revoked and banned.", parse_mode="Markdown")

@bot.message_handler(commands=['getlogs'])
def cmd_getlogs(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Unauthorised.")
        return
    found = False
    if os.path.exists("usage_logs.csv"):
        with open("usage_logs.csv", "rb") as f:
            bot.send_document(message.chat.id, f, caption="📊 Usage Logs")
        found = True
    if os.path.exists("report_issue.csv"):
        with open("report_issue.csv", "rb") as f:
            bot.send_document(message.chat.id, f, caption="🚩 Issue Reports")
        found = True
    if not found:
        bot.reply_to(message, "❌ No logs generated yet.")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    base = (
        "*Airtel Field Bot — Help*\n\n"
        "*🏘 Building Info*\n"
        "Search society penetration data.\n"
        "Enter RSU code, then building name.\n"
        "Example: `MWE Sneha Sadan`\n\n"
        "*📡 Area RFS Info*\n"
        "Find buildings near you.\n"
        "Send your location after selecting this mode.\n\n"
        "*TIPS:*\n"
        "— RSU code must be correct\n"
        "— You can type part of the building name\n"
        "— Contact your TM if your RSU code is unknown\n"
        "— Sessions expire after 12 hours"
    )
    if is_admin(message.from_user.id):
        base += (
            "\n\n*Admin Commands:*\n"
            "`/users` — list all authorised agents\n"
            "`/revoke OLM_ID` — revoke agent access\n"
            "`/getlogs` — download usage and issue logs"
        )
    bot.send_message(message.chat.id, base, parse_mode="Markdown")

# ==========================================
# 6. /start
# ==========================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id

    if is_authenticated(user_id):
        name = get_session(user_id).get('name', 'Agent')
        bot.send_message(
            message.chat.id,
            f"👋 Welcome back, *{name}!*\n\nWhat would you like to do?",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        return

    msg = bot.send_message(
        message.chat.id,
        "👋 *Welcome to the Airtel Field Bot.*\n\nPlease enter your *OLM ID* to continue:\n_(Format: A1234567)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, handle_olm_login)

# ==========================================
# 7. OLM ID LOGIN
# ==========================================

def handle_olm_login(message):
    user_id = message.from_user.id
    olm_input = message.text.strip().upper()

    # Check banned first
    if olm_input in BANNED_OLM_IDS:
        bot.send_message(
            message.chat.id,
            "⛔ *Your access has been revoked.*\n\nContact your TM for more information.",
            parse_mode="Markdown"
        )
        return

    if not validate_olm(olm_input):
        msg = bot.send_message(
            message.chat.id,
            "❌ *Invalid OLM ID.*\n\nFormat: `A` followed by 7 digits.\nExample: `A1234567`\n\nPlease try again:",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, handle_olm_login)
        return

    if olm_input in AGENT_MAP:
        # Authorised — log in
        name = AGENT_MAP[olm_input]
        sessions[user_id] = {
            'olm_id':    olm_input,
            'name':      name,
            'timestamp': time.time(),
            'mode':      None,
            'rsu':       None
        }
        log_usage(user_id, name, "Login", olm_input, "Success")
        bot.send_message(
            message.chat.id,
            f"✅ *Welcome, {name}!* You are now logged in.\n\nWhat would you like to do?",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
    else:
        # Not recognised — offer access request
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("✋ Request Access", callback_data=f"request_{olm_input}"))
        bot.send_message(
            message.chat.id,
            f"❌ *OLM ID `{olm_input}` not recognised.*\n\nIf you are a new agent, tap below to request access.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

# ==========================================
# 8. ACCESS REQUEST FLOW
# ==========================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("request_"))
def handle_access_request(call):
    olm_id = call.data.replace("request_", "")
    msg = bot.send_message(
        call.message.chat.id,
        "📝 *New Agent Registration*\n\nPlease reply with the following details, each on a new line:\n\n"
        "1. Full Name\n"
        "2. OLM ID\n"
        "3. Role\n"
        "4. SM/TM Name\n"
        "5. Date of Joining",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, submit_request, olm_id)
    bot.answer_callback_query(call.id)

def submit_request(message, olm_id):
    if not message.text:
        bot.reply_to(message, "❌ Cancelled. Please send text only.")
        return

    user_id = message.from_user.id
    details = message.text.strip()

    # Send to all admins
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{olm_id}"),
        InlineKeyboardButton("❌ Deny",    callback_data=f"deny_{user_id}_{olm_id}")
    )
    admin_msg = (
        f"🔔 *New Access Request*\n\n"
        f"🆔 Telegram ID: `{user_id}`\n"
        f"📋 OLM ID: `{olm_id}`\n\n"
        f"📝 *Details:*\n{details}"
    )
    notify_admins(admin_msg, keyboard)

    bot.reply_to(
        message,
        "⏳ *Request Sent.*\n\nYour details have been forwarded to the admin. You will be notified once approved.",
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith(("approve_", "deny_")))
def handle_admin_decision(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Unauthorised.")
        return

    parts = call.data.split("_")
    action   = parts[0]
    target_id = int(parts[1])
    olm_id   = parts[2]

    if action == "approve":
        # Extract name from the request message text
        # First line after "Details:" is Full Name
        try:
            msg_text = call.message.text
            details_section = msg_text.split("Details:")[1].strip()
            first_line = details_section.split("\n")[0].strip()
            name = first_line
        except:
            name = olm_id

        save_agent_to_csv(olm_id, name)

        bot.edit_message_text(
            f"✅ *Approved.*\n`{olm_id}` — {name} has been added.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        try:
            bot.send_message(
                target_id,
                "🎉 *Access Granted!*\n\nYour account has been approved. Type /start to log in.",
                parse_mode="Markdown"
            )
        except:
            pass

    elif action == "deny":
        bot.edit_message_text(
            f"❌ *Denied.*\n`{olm_id}` request has been rejected.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        try:
            bot.send_message(
                target_id,
                "⛔ *Access Denied.*\n\nYour request was declined. Contact your TM for more information.",
                parse_mode="Markdown"
            )
        except:
            pass

    bot.answer_callback_query(call.id)

# ==========================================
# 9. MODE SELECTION
# ==========================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("mode_"))
def handle_mode(call):
    user_id = call.from_user.id

    if not is_authenticated(user_id):
        bot.answer_callback_query(call.id, "⛔ Session expired. Type /start.")
        return

    mode = call.data.replace("mode_", "")
    sessions[user_id]['mode'] = mode

    if mode == "society":
        bot.edit_message_text(
            "🏘 *Building Info*\n\nEnter your *RSU code:*\n_(e.g. MWE, ANE, THW)_",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(call.message, handle_rsu_input)

    elif mode == "rfs":
        bot.edit_message_text(
            "📡 *Area RFS Info*\n\nTap the 📎 icon and send your *current location* to scan for buildings within 200m.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        sessions[user_id]['step'] = 'awaiting_location'

    bot.answer_callback_query(call.id)

# ==========================================
# 10. SOCIETY BOT — RSU + BUILDING SEARCH
# ==========================================

def handle_rsu_input(message):
    user_id = message.from_user.id
    if not is_authenticated(user_id):
        bot.reply_to(message, "⛔ Session expired. Type /start.")
        return
    rsu = message.text.strip().upper()
    sessions[user_id]['rsu'] = rsu
    msg = bot.send_message(
        message.chat.id,
        f"📍 RSU: *{rsu}*\n\nNow enter the *building name* _(or part of it)_:",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, handle_building_search)

def handle_building_search(message):
    user_id = message.from_user.id
    if not is_authenticated(user_id):
        bot.reply_to(message, "⛔ Session expired. Type /start.")
        return

    building_query = message.text.strip()
    rsu = sessions[user_id].get('rsu', '')
    session = sessions[user_id]

    if df_society.empty:
        bot.reply_to(message, "❌ Society database not loaded. Contact admin.")
        return

    results = df_society[
        (df_society['rsu'].astype(str).str.upper() == rsu) &
        (df_society['building_name'].astype(str).str.upper().str.contains(
            building_query.upper(), regex=False
        ))
    ]

    log_usage(user_id, session.get('name', ''), "Society_Search",
              f"{rsu} | {building_query}", f"{len(results)} results")

    if results.empty:
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🔁 Search Again", callback_data="mode_society"),
            InlineKeyboardButton("🏠 Main Menu",    callback_data="go_home")
        )
        bot.send_message(
            message.chat.id,
            f"❌ No buildings found for *{building_query}* in RSU *{rsu}*.\n\n"
            f"Tips:\n— Check your RSU code\n— Try a shorter name\n— Try just one word",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    if len(results) == 1:
        send_society_card(message.chat.id, results.iloc[0], rsu, user_id)
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    response = f"Found *{len(results)}* matches in RSU *{rsu}*:\n\n"
    for i, (idx, row) in enumerate(results.head(8).iterrows(), 1):
        name = str(row['building_name'])
        loc  = str(row.get('locality', ''))
        response += f"{i}. {name} — {loc}\n"
        keyboard.add(InlineKeyboardButton(f"🏢 {name}", callback_data=f"soc_{idx}"))
    response += "\nDid you mean one of these? Tap to view details."
    keyboard.add(InlineKeyboardButton("🏠 Main Menu", callback_data="go_home"))
    bot.send_message(message.chat.id, response, parse_mode="Markdown", reply_markup=keyboard)

def send_society_card(chat_id, row, rsu, user_id):
    name     = str(row.get('building_name', 'N/A'))
    btype    = str(row.get('building_type', 'N/A'))
    loc      = str(row.get('locality', 'N/A'))
    total    = int(row['total_units'])           if pd.notna(row.get('total_units'))           else 0
    postpaid = int(row['airtel_postpaid_users'])  if pd.notna(row.get('airtel_postpaid_users'))  else 0
    prepaid  = int(row['airtel_prepaid_users'])   if pd.notna(row.get('airtel_prepaid_users'))   else 0
    wifi     = int(row['airtel_wifi_users'])      if pd.notna(row.get('airtel_wifi_users'))      else 0
    oap      = int(row['airtel_oap_users'])       if pd.notna(row.get('airtel_oap_users'))       else 0
    comp     = int(row['competition_users'])      if pd.notna(row.get('competition_users'))      else 0

    not_on_wifi     = total - wifi
    not_on_postpaid = total - postpaid

    def fmt(val):
        return str(val) if val else "N/A"

    msg = (
        f"🏢 *{name}*\n"
        f"Type: {btype}\n"
        f"Location: {loc} [{rsu}]\n\n"
        f"🏠 Total Flats: *{total}*\n\n"
        f"📶 *Airtel Penetration:*\n"
        f"  WiFi: {fmt(wifi)}\n"
        f"  OAP: {fmt(oap)}\n"
        f"  Postpaid: {fmt(postpaid)}\n"
        f"  Prepaid: {fmt(prepaid)}\n"
        f"  Competition: {fmt(comp)}\n\n"
        f"💡 *Opportunity:*\n"
        f"  Not on Airtel WiFi: *{not_on_wifi}*\n"
        f"  Not on Airtel Postpaid: *{not_on_postpaid}*"
    )

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🚩 Report Issue",  callback_data=f"report_soc_{name[:30]}"),
        InlineKeyboardButton("🔁 Search Again",  callback_data="mode_society"),
        InlineKeyboardButton("🏠 Main Menu",     callback_data="go_home")
    )

    log_usage(user_id, sessions.get(user_id, {}).get('name', ''), "Society_View", name, "Success")
    bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("soc_"))
def handle_society_detail(call):
    user_id = call.from_user.id
    if not is_authenticated(user_id):
        bot.answer_callback_query(call.id, "⛔ Session expired. Type /start.")
        return
    idx = int(call.data.replace("soc_", ""))
    row = df_society.loc[idx]
    rsu = sessions[user_id].get('rsu', '')
    send_society_card(call.message.chat.id, row, rsu, user_id)
    bot.answer_callback_query(call.id)

# ==========================================
# 11. RFS BOT — LOCATION SCAN
# ==========================================

@bot.message_handler(content_types=['location'])
def handle_location(message):
    user_id = message.from_user.id
    if not is_authenticated(user_id):
        bot.reply_to(message, "⛔ Please type /start to log in first.")
        return

    session = sessions.get(user_id, {})
    if session.get('mode') != 'rfs':
        bot.reply_to(message, "ℹ️ Location received, but you're not in RFS mode.\n\nChoose a mode:", reply_markup=get_main_menu())
        return

    if not RFS_BUILDINGS:
        bot.reply_to(message, "❌ RFS database not loaded. Contact admin.")
        return

    user_coords = (message.location.latitude, message.location.longitude)
    bot.reply_to(message, "📍 Scanning for buildings within 200m...")

    nearby = []
    for bldg in RFS_BUILDINGS:
        try:
            lat = float(bldg.get('Latitude', 0))
            lon = float(bldg.get('Longitude', 0))
            if lat and lon:
                dist = geodesic(user_coords, (lat, lon)).kilometers
                if dist <= 0.2:
                    nearby.append({'data': bldg, 'distance': int(dist * 1000)})
        except (ValueError, TypeError):
            continue

    nearby.sort(key=lambda x: x['distance'])
    log_usage(user_id, session.get('name', ''), "RFS_Scan",
              f"{user_coords[0]:.4f},{user_coords[1]:.4f}", f"Found {len(nearby)}")

    if not nearby:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🏠 Main Menu", callback_data="go_home"))
        bot.send_message(message.chat.id, "❌ No buildings found within 200m.", reply_markup=keyboard)
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    for item in nearby:
        bldg = item['data']
        dist = item['distance']
        name = bldg.get('Building_Name', bldg.get('Building RSU', 'Unknown'))
        keyboard.add(InlineKeyboardButton(f"🏢 {name} ({dist}m)", callback_data=f"rfs_{bldg['Row_Index']}"))
    keyboard.add(InlineKeyboardButton("🏠 Main Menu", callback_data="go_home"))

    bot.send_message(message.chat.id, f"✅ Found *{len(nearby)}* building(s) nearby. Tap to view:",
                     parse_mode="Markdown", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rfs_"))
def handle_rfs_detail(call):
    user_id = call.from_user.id
    if not is_authenticated(user_id):
        bot.answer_callback_query(call.id, "⛔ Session expired. Type /start.")
        return

    row_index = int(call.data.replace("rfs_", ""))
    bldg = next((b for b in RFS_BUILDINGS if b['Row_Index'] == row_index), None)
    if not bldg:
        bot.answer_callback_query(call.id, "❌ Building not found.")
        return

    session = sessions.get(user_id, {})
    name = bldg.get('Building_Name', 'Unknown')
    rsu  = bldg.get('Building RSU', 'N/A')
    lat  = bldg.get('Latitude')
    lon  = bldg.get('Longitude')

    msg = (
        f"📊 *{name}*\n"
        f"🔖 RSU: `{rsu}`\n"
        f"📍 Type: {bldg.get('Location Type', 'N/A')} | {bldg.get('Final Tagging', 'N/A')}\n"
        f"🚦 RFS Status: *{bldg.get('RFS_Status', 'N/A')}*\n"
        f"─────────────────────\n"
        f"🏠 Total HPs: *{bldg.get('Total HPs', 0)}*\n"
        f"🟢 Actual Util: {bldg.get('Actual Util Count', 0)}\n"
        f"📊 Util %: {bldg.get('Util %', 'N/A')}\n"
        f"🔥 Total Spare: *{bldg.get('Total Spare', 0)}*"
    )

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🗺 Get Directions", url=f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"),
        InlineKeyboardButton("🚩 Report Issue",   callback_data=f"report_rfs_{row_index}")
    )
    keyboard.add(InlineKeyboardButton("🏠 Main Menu", callback_data="go_home"))

    log_usage(user_id, session.get('name', ''), "RFS_View", name, "Success")
    bot.send_message(call.message.chat.id, msg, parse_mode="Markdown", reply_markup=keyboard)
    bot.answer_callback_query(call.id)

# ==========================================
# 12. REPORT ISSUE — BOTH MODES
# ==========================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("report_rfs_"))
def handle_report_rfs(call):
    user_id = call.from_user.id
    row_index = int(call.data.replace("report_rfs_", ""))
    bldg = next((b for b in RFS_BUILDINGS if b['Row_Index'] == row_index), None)
    if bldg:
        name = bldg.get('Building_Name', 'Unknown')
        msg = bot.send_message(
            call.message.chat.id,
            f"🚩 *Reporting issue for:* {name}\n\nType a short description:",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, save_issue_rfs, name)
    bot.answer_callback_query(call.id)

def save_issue_rfs(message, building_name):
    if not message.text:
        bot.reply_to(message, "❌ Cancelled. Please send text only.")
        return
    session = sessions.get(message.from_user.id, {})
    save_report(message.from_user.id, session.get('name', ''),
                session.get('olm_id', ''), building_name, "RFS", message.text)
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🏠 Main Menu", callback_data="go_home"))
    bot.reply_to(message, "✅ *Issue logged successfully.*", parse_mode="Markdown", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("report_soc_"))
def handle_report_soc(call):
    building_name = call.data.replace("report_soc_", "")
    msg = bot.send_message(
        call.message.chat.id,
        f"🚩 *Reporting issue for:* {building_name}\n\nType a short description:\n_(e.g. wrong unit count, building doesn't exist)_",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, save_issue_soc, building_name)
    bot.answer_callback_query(call.id)

def save_issue_soc(message, building_name):
    if not message.text:
        bot.reply_to(message, "❌ Cancelled. Please send text only.")
        return
    session = sessions.get(message.from_user.id, {})
    save_report(message.from_user.id, session.get('name', ''),
                session.get('olm_id', ''), building_name, "Society", message.text)
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🏠 Main Menu", callback_data="go_home"))
    bot.reply_to(message, "✅ *Issue logged successfully.*", parse_mode="Markdown", reply_markup=keyboard)

# ==========================================
# 13. GO HOME
# ==========================================

@bot.callback_query_handler(func=lambda call: call.data == "go_home")
def go_home(call):
    user_id = call.from_user.id
    if not is_authenticated(user_id):
        bot.answer_callback_query(call.id, "⛔ Session expired. Type /start.")
        return
    sessions[user_id]['mode'] = None
    sessions[user_id]['rsu']  = None
    name = sessions[user_id].get('name', 'Agent')
    bot.send_message(
        call.message.chat.id,
        f"🏠 *Main Menu*\n\nWhat would you like to do, {name}?",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )
    bot.answer_callback_query(call.id)

# ==========================================
# 14. FALLBACK
# ==========================================

@bot.message_handler(func=lambda message: True)
def fallback(message):
    user_id = message.from_user.id
    if not is_authenticated(user_id):
        bot.reply_to(message, "👋 Type /start to log in.")
        return
    mode = sessions.get(user_id, {}).get('mode')
    if mode == 'rfs':
        bot.reply_to(message, "📡 You're in RFS mode. Please *send your location* using the 📎 icon.", parse_mode="Markdown")
    else:
        bot.reply_to(message, "Please choose a mode from the menu:", reply_markup=get_main_menu())

# ==========================================
# 15. RUN
# ==========================================

print("🚀 Unified Airtel Field Bot is online!")
import telebot
telebot.apihelper.SESSION_TIME_TO_LIVE = 5 * 60
bot.infinity_polling(timeout=10, long_polling_timeout=5)


