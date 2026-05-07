import os
import re
import threading
import sqlite3
from datetime import datetime

from flask import Flask, render_template, jsonify, send_from_directory, abort
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

app = Flask(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "database.db")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

SUBJECTS = [
    "اقتصاد المؤسسة",
    "الاقتصاد الجزئي 2",
    "الرياضيات 2",
    "الإحصاء 2",
    "تاريخ الفكر الاقتصادي",
    "أساسيات البرمجة بايثون 2",
    "المحاسبة المالية 2",
    "المصطلحات الاقتصادية بالإنجليزية",
    "القانون التجاري",
]

CATEGORIES = ["Cours", "TD", "TP", "Summary"]

EXAMS = [
    {"subject": "أساسيات البرمجة بالبايثون", "date": "2026-05-09", "time": "08:30", "session": "صباحية"},
    {"subject": "اقتصاد جزئي 2", "date": "2026-05-10", "time": "08:30", "session": "صباحية"},
    {"subject": "قانون تجاري", "date": "2026-05-11", "time": "08:30", "session": "صباحية"},
    {"subject": "إحصاء 2", "date": "2026-05-12", "time": "08:30", "session": "صباحية"},
    {"subject": "انجليزية 2", "date": "2026-05-13", "time": "08:30", "session": "صباحية"},
    {"subject": "محاسبة 2", "date": "2026-05-14", "time": "08:30", "session": "صباحية"},
    {"subject": "تاريخ الفكر الاقتصادي", "date": "2026-05-16", "time": "14:00", "session": "مسائية"},
    {"subject": "رياضيات 2", "date": "2026-05-17", "time": "14:00", "session": "مسائية"},
    {"subject": "اقتصاد المؤسسة", "date": "2026-05-18", "time": "14:00", "session": "مسائية"},
]

# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            category TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            saved_filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_file_record(subject, category, original_name, saved_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO files (subject, category, original_filename, saved_filename, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (subject, category, original_name, saved_name, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_files_by_subject():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT subject, category, original_filename, saved_filename FROM files ORDER BY uploaded_at DESC")
    rows = c.fetchall()
    conn.close()

    result = {}
    for row in rows:
        subj, cat, orig, saved = row
        if subj not in result:
            result[subj] = {"Cours": [], "TD": [], "TP": [], "Summary": []}
        if cat in result[subj]:
            result[subj][cat].append({
                "original": orig,
                "saved": saved,
            })
    return result


def get_recent_files(limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, subject, category, original_filename, saved_filename, uploaded_at FROM files ORDER BY uploaded_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def delete_file_record(file_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT saved_filename, subject FROM files WHERE id = ?", (file_id,))
    row = c.fetchone()
    if row:
        saved_name, subject = row
        c.execute("DELETE FROM files WHERE id = ?", (file_id,))
        conn.commit()
        conn.close()
        return saved_name, subject
    conn.close()
    return None, None


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    if len(name) > 120:
        base, ext = os.path.splitext(name)
        name = base[:100] + ext
    return name

# ── Flask Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", subjects=SUBJECTS, exams=EXAMS)


@app.route("/api/files")
def api_files():
    return jsonify(get_files_by_subject())


@app.route("/uploads/<path:filename>")
def serve_file(filename):
    directory = os.path.dirname(os.path.join(UPLOAD_FOLDER, filename))
    file_only = os.path.basename(filename)
    if not os.path.exists(os.path.join(directory, file_only)):
        abort(404)
    return send_from_directory(directory, file_only, as_attachment=False)


@app.route("/download/<path:filename>")
def download_file(filename):
    directory = os.path.dirname(os.path.join(UPLOAD_FOLDER, filename))
    file_only = os.path.basename(filename)
    if not os.path.exists(os.path.join(directory, file_only)):
        abort(404)
    return send_from_directory(directory, file_only, as_attachment=True)

# ── Telegram Bot ──────────────────────────────────────────────────────────────

def is_admin(message):
    return message.from_user.id == ADMIN_ID


def subject_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    for i, s in enumerate(SUBJECTS):
        markup.add(InlineKeyboardButton(text=s, callback_data=f"subj_{i}"))
    return markup


def category_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for i, c in enumerate(CATEGORIES):
        markup.add(InlineKeyboardButton(text=c, callback_data=f"cat_{i}"))
    return markup


if bot:
    @bot.message_handler(commands=["start"])
    def handle_start(message):
        if not is_admin(message):
            bot.reply_to(message, "You are not authorized to use this bot.")
            return
        bot.reply_to(message, "Welcome, Admin! Choose a subject to upload a file:", reply_markup=subject_keyboard())

    # Store user state: {chat_id: {"subject": ..., "category": ..., "filename": ...}}
    user_state = {}

    @bot.callback_query_handler(func=lambda call: call.data.startswith("subj_"))
    def handle_subject_choice(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Unauthorized")
            return
        idx = int(call.data[len("subj_"):])
        subject = SUBJECTS[idx]
        user_state[call.from_user.id] = {"subject": subject}
        bot.edit_message_text(
            f"Subject selected: {subject}\nNow choose a category:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=category_keyboard(),
        )
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("cat_"))
    def handle_category_choice(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Unauthorized")
            return
        idx = int(call.data[len("cat_"):])
        category = CATEGORIES[idx]
        state = user_state.get(call.from_user.id)
        if not state or "subject" not in state:
            bot.edit_message_text("Please start over with /start", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return
        state["category"] = category
        user_state[call.from_user.id] = state
        bot.edit_message_text(
            f"Subject: {state['subject']}\nCategory: {category}\n\nNow send me the file (PDF or image).",
            call.message.chat.id,
            call.message.message_id,
        )
        bot.answer_callback_query(call.id)

    @bot.message_handler(commands=["delete"])
    def handle_delete(message):
        if not is_admin(message):
            bot.reply_to(message, "You are not authorized.")
            return
        files = get_recent_files(50)
        if not files:
            bot.reply_to(message, "No files found.")
            return

        markup = InlineKeyboardMarkup(row_width=1)
        for f in files[:20]:
            f_id, subj, cat, orig, saved, ts = f
            label = f"[{subj[:20]}..] {cat} - {orig[:25]}"
            markup.add(InlineKeyboardButton(text=label, callback_data=f"del_{f_id}"))
        bot.reply_to(
            message,
            "🗑 Select a file to delete (showing latest 20):",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("del_"))
    def handle_delete_confirm(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Unauthorized")
            return
        file_id = int(call.data[len("del_"):])
        saved_name, subject = delete_file_record(file_id)
        if saved_name:
            file_path = os.path.join(UPLOAD_FOLDER, subject, saved_name)
            if os.path.exists(file_path):
                os.remove(file_path)
            bot.edit_message_text(
                f"✅ File deleted successfully.",
                call.message.chat.id,
                call.message.message_id,
            )
        else:
            bot.edit_message_text(
                "File not found or already deleted.",
                call.message.chat.id,
                call.message.message_id,
            )
        bot.answer_callback_query(call.id)

    @bot.message_handler(content_types=["document", "photo"])
    def handle_file(message):
        if not is_admin(message):
            bot.reply_to(message, "You are not authorized.")
            return

        state = user_state.get(message.from_user.id)
        if not state or "subject" not in state or "category" not in state:
            bot.reply_to(
                message,
                "Please use /start first to choose a subject and category before sending a file.",
            )
            return

        subject = state["subject"]
        category = state["category"]

        if message.content_type == "document":
            file_info = bot.get_file(message.document.file_id)
            original_name = message.document.file_name or "document"
        else:
            file_info = bot.get_file(message.photo[-1].file_id)
            original_name = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

        downloaded_file = bot.download_file(file_info.file_path)
        safe_name = sanitize_filename(original_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_name = f"{timestamp}_{safe_name}"

        subject_folder = os.path.join(UPLOAD_FOLDER, subject)
        os.makedirs(subject_folder, exist_ok=True)
        file_path = os.path.join(subject_folder, saved_name)

        with open(file_path, "wb") as f:
            f.write(downloaded_file)

        save_file_record(subject, category, original_name, saved_name)

        bot.reply_to(
            message,
            f"✅ File saved!\n\nSubject: {subject}\nCategory: {category}\nFile: {original_name}\n\nYou can send more files for the same subject/category.\nUse /start to change subject or category.",
        )


def run_bot():
    if bot:
        try:
            bot.remove_webhook()
        except:
            pass
        bot.infinity_polling(skip_pending=True, interval=0.5, timeout=20)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    if bot and ADMIN_ID:
        t = threading.Thread(target=run_bot, daemon=True)
        t.start()
        print("Bot polling started in background thread.")
    else:
        print("Bot not configured. Set TELEGRAM_BOT_TOKEN and ADMIN_ID in .env")

    port = int(os.getenv("PORT", 5000))
    print(f"Flask server running on port {port}")
    app.run(debug=False, port=port, host="0.0.0.0")
