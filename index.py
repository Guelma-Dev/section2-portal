import os
import re
import json
import threading
import urllib.request
from urllib.parse import unquote
from datetime import datetime

from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import cloudinary
import cloudinary.uploader
import cloudinary.utils
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

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


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            subject TEXT NOT NULL,
            category TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            cloudinary_url TEXT NOT NULL,
            cloudinary_public_id TEXT NOT NULL,
            resource_type TEXT DEFAULT 'raw',
            uploaded_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def migrate_old_urls():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, cloudinary_url FROM files WHERE cloudinary_url LIKE '%/s--%'")
    rows = c.fetchall()
    for row in rows:
        unsigned_url = re.sub(r'/s--[^/]+--/', '/', row["cloudinary_url"])
        c.execute("UPDATE files SET cloudinary_url = %s WHERE id = %s", (unsigned_url, row["id"]))
    if rows:
        conn.commit()
    conn.close()


def save_file_record(subject, category, original_name, cloudinary_url, cloudinary_public_id, resource_type):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO files (subject, category, original_filename, cloudinary_url, cloudinary_public_id, resource_type, uploaded_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (subject, category, original_name, cloudinary_url, cloudinary_public_id, resource_type, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_files_by_subject():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT subject, category, original_filename, cloudinary_url, cloudinary_public_id, resource_type FROM files ORDER BY uploaded_at DESC")
    rows = c.fetchall()
    conn.close()
    result = {}
    for row in rows:
        subj = row["subject"]
        cat = row["category"]
        if subj not in result:
            result[subj] = {"Cours": [], "TD": [], "TP": [], "Summary": []}
        if cat in result[subj]:
            url = row["cloudinary_url"]
            download_url = url + "?fl_attachment=1"
            result[subj][cat].append({
                "original": row["original_filename"],
                "url": url,
                "download_url": download_url,
            })
    return result


def get_recent_files(limit=20):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, subject, category, original_filename, cloudinary_url, cloudinary_public_id, uploaded_at FROM files ORDER BY uploaded_at DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    conn.close()
    return [(r["id"], r["subject"], r["category"], r["original_filename"], r["cloudinary_url"], r["uploaded_at"]) for r in rows]


def delete_file_record(file_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT cloudinary_public_id, resource_type, subject FROM files WHERE id = %s", (file_id,))
    row = c.fetchone()
    if row:
        public_id = row["cloudinary_public_id"]
        resource_type = row["resource_type"]
        subject = row["subject"]
        c.execute("DELETE FROM files WHERE id = %s", (file_id,))
        conn.commit()
        conn.close()
        try:
            cloudinary.uploader.destroy(public_id, resource_type=resource_type)
        except:
            pass
        return public_id, subject
    conn.close()
    return None, None


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    if len(name) > 120:
        base, ext = os.path.splitext(name)
        name = base[:100] + ext
    return name


@app.route("/")
def index():
    return render_template("index.html", subjects=SUBJECTS, exams=EXAMS)


@app.route("/api/files")
def api_files():
    return jsonify(get_files_by_subject())


@app.route("/api/migrate")
def api_migrate():
    if str(ADMIN_ID) not in (request.args.get("key") or ""):
        return jsonify({"error": "unauthorized"}), 403
    old_url = "https://section2-portal-1.onrender.com/api/files"
    try:
        resp = urllib.request.urlopen(old_url, timeout=15)
        data = json.loads(resp.read())
    except Exception as e:
        return jsonify({"error": f"fetch failed: {e}"}), 502
    conn = get_db()
    c = conn.cursor()
    count = 0
    for subject, categories in data.items():
        for category, files in categories.items():
            for f in files:
                url = f["url"]
                m = re.match(r'https://res\.cloudinary\.com/[^/]+/([^/]+)/upload/v\d+/(.+)', url)
                if not m:
                    continue
                resource_type = m.group(1)
                public_id = unquote(m.group(2))
                c.execute(
                    "SELECT COUNT(*) AS cnt FROM files WHERE cloudinary_public_id = %s",
                    (public_id,),
                )
                if c.fetchone()["cnt"] > 0:
                    continue
                c.execute(
                    "INSERT INTO files (subject, category, original_filename, cloudinary_url, cloudinary_public_id, resource_type, uploaded_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (subject, category, f["original"], url, public_id, resource_type, datetime.now().isoformat()),
                )
                count += 1
    conn.commit()
    conn.close()
    return jsonify({"migrated": count})


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

    user_state = {}

    @bot.callback_query_handler(func=lambda call: call.data.startswith("subj_"))
    def handle_subject_choice(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Unauthorized")
            return
        idx = int(call.data[len("subj_"):])
        subject = SUBJECTS[idx]
        user_state[call.from_user.id] = {"subject": subject}
        bot.edit_message_text(f"Subject selected: {subject}\nNow choose a category:", call.message.chat.id, call.message.message_id, reply_markup=category_keyboard())
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
        bot.edit_message_text(f"Subject: {state['subject']}\nCategory: {category}\n\nNow send me the file (PDF or image).", call.message.chat.id, call.message.message_id)
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
            f_id, subj, cat, orig, url, ts = f
            label = f"[{subj[:20]}..] {cat} - {orig[:25]}"
            markup.add(InlineKeyboardButton(text=label, callback_data=f"del_{f_id}"))
        bot.reply_to(message, "Select a file to delete (showing latest 20):", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("del_"))
    def handle_delete_confirm(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Unauthorized")
            return
        file_id = int(call.data[len("del_"):])
        public_id, subject = delete_file_record(file_id)
        if public_id:
            bot.edit_message_text("File deleted successfully.", call.message.chat.id, call.message.message_id)
        else:
            bot.edit_message_text("File not found or already deleted.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)

    @bot.message_handler(content_types=["document", "photo"])
    def handle_file(message):
        if not is_admin(message):
            bot.reply_to(message, "You are not authorized.")
            return
        state = user_state.get(message.from_user.id)
        if not state or "subject" not in state or "category" not in state:
            bot.reply_to(message, "Please use /start first to choose a subject and category before sending a file.")
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
        public_id = f"{subject}/{timestamp}_{safe_name}"
        ext = os.path.splitext(original_name)[1].lower()
        resource_type = "image" if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'] else "raw"
        upload_result = cloudinary.uploader.upload(
            downloaded_file,
            resource_type=resource_type,
            public_id=public_id,
            overwrite=True,
        )
        save_file_record(subject, category, original_name, upload_result["secure_url"], upload_result["public_id"], upload_result.get("resource_type", resource_type))
        bot.reply_to(message, f"File saved!\n\nSubject: {subject}\nCategory: {category}\nFile: {original_name}\n\nSend more files or use /start to change.")


def run_bot():
    if bot:
        try:
            bot.remove_webhook()
        except:
            pass
        bot.infinity_polling(skip_pending=True, interval=0.5, timeout=20)


if __name__ == "__main__":
    try:
        init_db()
        migrate_old_urls()
    except Exception as e:
        print(f"ERROR init_db: {e}")
        raise
    if bot and ADMIN_ID:
        t = threading.Thread(target=run_bot, daemon=True)
        t.start()
        print("Bot polling started.")
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")
