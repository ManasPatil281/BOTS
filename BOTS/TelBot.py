import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os
from flask import Flask, request

# Initialize Flask app for webhook
app = Flask(__name__)

# Initialize Telegram bot
BOT_TOKEN = os.getenv('Tele_Bot')  # Use env var for security
bot = telebot.TeleBot(BOT_TOKEN)

# Initialize Firebase (if not already initialized)
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate('BOTS/firebase.json')
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        print("Please ensure 'firebase.json' is in the correct location.")
        exit(1)  # Exit if Firebase can't be initialized

db = firestore.client()

# User session storage
user_sessions = {}

class TelegramBot:
    def __init__(self):
        self.menu_options = {
            'complaint': '📝 Report a Complaint',
            'progress': '📈 Update Progress',
            'status': '🔍 Check Status'
        }
    
    def create_main_menu(self):
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📝 Report a Complaint", callback_data="complaint"),
            types.InlineKeyboardButton("📈 Update Progress", callback_data="progress"),
            types.InlineKeyboardButton("🔍 Check Status", callback_data="status")
        )
        return markup
    
    def save_to_firebase(self, collection, data):
        try:
            doc_ref = db.collection(collection).add(data)
            return doc_ref[1].id
        except Exception as e:
            print(f"Error saving to Firebase: {e}")
            return None

telegram_bot_handler = TelegramBot()

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = "🤖 Welcome to the Support Bot!\n\nPlease select an option below:"
    bot.reply_to(message, welcome_text, reply_markup=telegram_bot_handler.create_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    
    if call.data == "complaint":
        user_sessions[user_id] = {'state': 'awaiting_complaint'}
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📝 Please describe your complaint in detail:")
    
    elif call.data == "progress":
        user_sessions[user_id] = {'state': 'awaiting_progress'}
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📈 Please provide your ticket ID and progress update:")
    
    elif call.data == "status":
        user_sessions[user_id] = {'state': 'awaiting_status_id'}
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔍 Please provide your ticket ID to check status:")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text
    
    # Check if user has an active session
    if user_id not in user_sessions:
        bot.reply_to(message, "Please use /start to begin.", reply_markup=telegram_bot_handler.create_main_menu())
        return
    
    session = user_sessions[user_id]
    
    if session['state'] == 'awaiting_complaint':
        handle_complaint(message, user_id, text)
    elif session['state'] == 'awaiting_progress':
        handle_progress_update(message, user_id, text)
    elif session['state'] == 'awaiting_status_id':
        handle_status_check(message, user_id, text)

def handle_complaint(message, user_id, text):
    complaint_data = {
        'user_id': user_id,
        'username': message.from_user.username or 'N/A',
        'complaint': text,
        'timestamp': datetime.now(),
        'status': 'open',
        'type': 'complaint'
    }
    
    doc_id = telegram_bot_handler.save_to_firebase('complaints', complaint_data)
    
    if doc_id:
        response_text = f"✅ Your complaint has been recorded!\n\n📋 Ticket ID: `{doc_id}`\n\nPlease save this ID for future reference."
        # Clear session
        del user_sessions[user_id]
    else:
        response_text = "❌ Error saving complaint. Please try again."
    
    bot.reply_to(message, response_text, reply_markup=telegram_bot_handler.create_main_menu(), parse_mode='Markdown')

def handle_progress_update(message, user_id, text):
    progress_data = {
        'user_id': user_id,
        'username': message.from_user.username or 'N/A',
        'progress_update': text,
        'timestamp': datetime.now(),
        'type': 'progress_update'
    }
    
    doc_id = telegram_bot_handler.save_to_firebase('progress_updates', progress_data)
    
    if doc_id:
        response_text = f"✅ Progress update recorded!\n\n📋 Update ID: `{doc_id}`"
        del user_sessions[user_id]
    else:
        response_text = "❌ Error saving progress update. Please try again."
    
    bot.reply_to(message, response_text, reply_markup=telegram_bot_handler.create_main_menu(), parse_mode='Markdown')

def handle_status_check(message, user_id, text):
    try:
        doc_ref = db.collection('complaints').document(text)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            response_text = f"📋 Status for Ticket ID: `{text}`\n\n"
            response_text += f"**Status:** {data.get('status', 'Unknown')}\n"
            response_text += f"**Created:** {data.get('timestamp', 'Unknown')}\n"
            response_text += f"**Type:** {data.get('type', 'Unknown')}"
        else:
            response_text = "❌ No record found with this Ticket ID."
    except Exception as e:
        response_text = "❌ Error checking status. Please verify the Ticket ID."
    
    del user_sessions[user_id]
    bot.reply_to(message, response_text, reply_markup=telegram_bot_handler.create_main_menu(), parse_mode='Markdown')

# Webhook endpoint for Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return '', 200

# Webhook setup for production (optional)
if __name__ == '__main__':
    # For local development (polling)
    # print("Bot is running...")
    # bot.polling(none_stop=True)
    
    # For production (webhook)
    WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # Set this in Render environment variables
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL + '/webhook')
        print("Webhook set. Running Flask app...")
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    else:
        print("WEBHOOK_URL not set. Running in polling mode...")
        bot.polling(none_stop=True)