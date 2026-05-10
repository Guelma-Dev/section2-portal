import os
import re
import json
import logging
from datetime import datetime

from flask import Flask, render_template, jsonify, request, send_from_directory
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
import cloudinary
import cloudinary.uploader
import cloudinary.utils
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.request
import urllib.error

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

GEMINI_KEY = os.getenv("GEMINI_API_KEY")

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
    c.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TEXT NOT NULL
        )
    """)
    try:
        c.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS downloads INTEGER DEFAULT 0")
    except:
        pass
    conn.commit()
    conn.close()


def migrate_old_urls():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, cloudinary_url, cloudinary_public_id, resource_type FROM files")
    rows = c.fetchall()
    for row in rows:
        url = row["cloudinary_url"]
        needs_fix = False
        if "/s--" in url:
            needs_fix = True
            url = re.sub(r'/s--[^/]+--/', '/', url)
        if "/v1/" in url:
            fixed = cloudinary.utils.cloudinary_url(row["cloudinary_public_id"], resource_type=row["resource_type"], secure=True, force_version=False)[0]
            if fixed != url:
                url = fixed
                needs_fix = True
        if needs_fix:
            c.execute("UPDATE files SET cloudinary_url = %s WHERE id = %s", (url, row["id"]))
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
    c.execute("SELECT id, subject, category, original_filename, cloudinary_url, cloudinary_public_id, resource_type, downloads FROM files ORDER BY uploaded_at DESC")
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
                "id": row["id"],
                "original": row["original_filename"],
                "url": url,
                "download_url": download_url,
                "downloads": row["downloads"] or 0,
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


def get_files_by_subject_and_subject(subject):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, original_filename, category FROM files WHERE subject = %s ORDER BY uploaded_at DESC", (subject,))
    rows = c.fetchall()
    conn.close()
    return rows


def add_announcement(content):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO announcements (content, enabled, created_at) VALUES (%s, TRUE, %s)", (content, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def delete_announcement(aid):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM announcements WHERE id = %s", (aid,))
    conn.commit()
    conn.close()


def get_announcements():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, content FROM announcements WHERE enabled = TRUE ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows


@app.route("/")
def index():
    return render_template("index.html", subjects=SUBJECTS, exams=EXAMS)


@app.route("/sw.js")
def sw_js():
    return send_from_directory(BASE_DIR, "sw.js", mimetype="application/javascript")


@app.route("/api/files")
def api_files():
    return jsonify(get_files_by_subject())


@app.route("/api/announcements")
def api_announcements():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT content FROM announcements WHERE enabled = TRUE ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify([r["content"] for r in rows])


@app.route("/api/files/popular")
def api_popular():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, subject, category, original_filename, cloudinary_url, downloads, uploaded_at FROM files ORDER BY downloads DESC, uploaded_at DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id":r["id"],"subject":r["subject"],"category":r["category"],"name":r["original_filename"],"url":r["cloudinary_url"],"downloads":r["downloads"] or 0,"time":r["uploaded_at"]} for r in rows])


@app.route("/api/recent")
def api_recent():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, subject, category, original_filename, cloudinary_url, uploaded_at FROM files ORDER BY uploaded_at DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id":r["id"],"subject":r["subject"],"category":r["category"],"name":r["original_filename"],"url":r["cloudinary_url"],"time":r["uploaded_at"]} for r in rows])


def main_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(text="📁 إضافة ملفات", callback_data="action_add"))
    markup.add(InlineKeyboardButton(text="🗑️ حذف ملفات", callback_data="action_delete"))
    markup.add(InlineKeyboardButton(text="📢 إعلان جديد", callback_data="action_announce"))
    markup.add(InlineKeyboardButton(text="❌ حذف إعلان", callback_data="action_delannounce"))
    return markup


def subject_keyboard(action):
    markup = InlineKeyboardMarkup(row_width=1)
    for i, s in enumerate(SUBJECTS):
        markup.add(InlineKeyboardButton(text=s, callback_data=f"{action}_{i}"))
    markup.add(InlineKeyboardButton(text="🔙 رجوع", callback_data="back_main"))
    return markup


def category_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for i, c in enumerate(CATEGORIES):
        markup.add(InlineKeyboardButton(text=c, callback_data=f"cat_{i}"))
    markup.add(InlineKeyboardButton(text="🔙 رجوع", callback_data="back_main"))
    return markup


if bot:
    user_state = {}

    def is_admin(message):
        return message.from_user.id == ADMIN_ID

    @bot.message_handler(commands=["start"])
    def handle_start(message):
        if not is_admin(message):
            bot.reply_to(message, "أنت غير مخول لاستخدام هذا البوت.")
            return
        user_state[message.from_user.id] = {}
        bot.reply_to(message, "مرحباً بك! اختر أمراً:", reply_markup=main_menu())

    @bot.callback_query_handler(func=lambda call: call.data == "back_main")
    def back_to_main(call):
        if call.from_user.id != ADMIN_ID:
            return
        user_state[call.from_user.id] = {}
        bot.edit_message_text("مرحباً بك! اختر أمراً:", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "action_add")
    def pick_subject_for_add(call):
        if call.from_user.id != ADMIN_ID:
            return
        bot.edit_message_text("اختر المادة:", call.message.chat.id, call.message.message_id, reply_markup=subject_keyboard("addupload"))
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("addupload_"))
    def handle_add_subject(call):
        if call.from_user.id != ADMIN_ID:
            return
        idx = int(call.data[len("addupload_"):])
        subject = SUBJECTS[idx]
        user_state[call.from_user.id] = {"subject": subject}
        bot.edit_message_text(f"المادة: {subject}\nاختر الفئة:", call.message.chat.id, call.message.message_id, reply_markup=category_keyboard())
        bot.answer_callback_query(call.id)

    # Re-use existing cat_ callbacks for upload flow
    @bot.callback_query_handler(func=lambda call: call.data.startswith("cat_"))
    def handle_category_choice(call):
        if call.from_user.id != ADMIN_ID:
            return
        idx = int(call.data[len("cat_"):])
        category = CATEGORIES[idx]
        state = user_state.get(call.from_user.id)
        if not state or "subject" not in state:
            bot.edit_message_text("الرجاء البدء من /start", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return
        state["category"] = category
        user_state[call.from_user.id] = state
        bot.edit_message_text(f"المادة: {state['subject']}\nالفئة: {category}\n\nأرسل الملف الآن:", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)

    # Delete flow: pick subject
    @bot.callback_query_handler(func=lambda call: call.data == "action_delete")
    def pick_subject_for_delete(call):
        if call.from_user.id != ADMIN_ID:
            return
        bot.edit_message_text("اختر المادة لحذف ملف:", call.message.chat.id, call.message.message_id, reply_markup=subject_keyboard("delsubj"))
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("delsubj_"))
    def show_files_for_delete(call):
        if call.from_user.id != ADMIN_ID:
            return
        idx = int(call.data[len("delsubj_"):])
        subject = SUBJECTS[idx]
        files = get_files_by_subject_and_subject(subject)
        if not files:
            bot.edit_message_text(f"لا توجد ملفات في {subject}.", call.message.chat.id, call.message.message_id, reply_markup=subject_keyboard("delsubj"))
            bot.answer_callback_query(call.id)
            return
        markup = InlineKeyboardMarkup(row_width=1)
        for f in files[:30]:
            f_id, orig, cat = f["id"], f["original_filename"], f["category"]
            label = f"{cat} - {orig[:35]}"
            markup.add(InlineKeyboardButton(text=label, callback_data=f"del_{f_id}"))
        markup.add(InlineKeyboardButton(text="🔙 رجوع", callback_data="action_delete"))
        bot.edit_message_text(f"اختر ملفاً للحذف من {subject}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("del_"))
    def handle_delete_confirm(call):
        if call.from_user.id != ADMIN_ID:
            return
        file_id = int(call.data[len("del_"):])
        public_id, subject = delete_file_record(file_id)
        if public_id:
            bot.edit_message_text(f"✅ تم حذف الملف بنجاح.", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
        else:
            bot.edit_message_text("الملف غير موجود.", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
        bot.answer_callback_query(call.id)

    # Announcement flow
    @bot.callback_query_handler(func=lambda call: call.data == "action_announce")
    def start_announce(call):
        if call.from_user.id != ADMIN_ID:
            return
        user_state[call.from_user.id] = {"awaiting_announce": True}
        bot.edit_message_text("أرسل نص الإعلان الذي تريد إضافته:", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "action_delannounce")
    def show_announcements(call):
        if call.from_user.id != ADMIN_ID:
            return
        announcements = get_announcements()
        if not announcements:
            bot.edit_message_text("لا توجد إعلانات.", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
            bot.answer_callback_query(call.id)
            return
        markup = InlineKeyboardMarkup(row_width=1)
        for a in announcements:
            markup.add(InlineKeyboardButton(text=a["content"][:40], callback_data=f"delann_{a['id']}"))
        markup.add(InlineKeyboardButton(text="🔙 رجوع", callback_data="back_main"))
        bot.edit_message_text("اختر إعلاناً لحذفه:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("delann_"))
    def delete_announce(call):
        if call.from_user.id != ADMIN_ID:
            return
        aid = int(call.data[len("delann_"):])
        delete_announcement(aid)
        bot.edit_message_text("✅ تم حذف الإعلان.", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
        bot.answer_callback_query(call.id)

    @bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("awaiting_announce"))
    def handle_announce_text(message):
        if not is_admin(message):
            return
        add_announcement(message.text)
        user_state[message.from_user.id] = {}
        bot.reply_to(message, "✅ تم إضافة الإعلان.", reply_markup=main_menu())

    @bot.message_handler(content_types=["document", "photo"])
    def handle_file(message):
        if not is_admin(message):
            bot.reply_to(message, "أنت غير مخول.")
            return
        state = user_state.get(message.from_user.id)
        if not state or "subject" not in state or "category" not in state:
            bot.reply_to(message, "الرجاء استخدام /start ثم اختيار إضافة ملفات.", reply_markup=main_menu())
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
        bot.reply_to(message, f"✅ تم حفظ الملف!\n\nالمادة: {subject}\nالفئة: {category}\nالملف: {original_name}", reply_markup=main_menu())


@app.route("/api/chat", methods=["POST"])
def api_chat():
    msg = request.json.get("message", "").strip()
    if not msg:
        return jsonify({"reply": "اكتب سؤالك 😊"})
    orig = msg
    msg_lower = msg.lower()

    # Build portal context for Gemini
    subj_list = "\n".join([f"- {s}" for s in SUBJECTS])
    exams_list = "\n".join([f"- {e['subject']}: {e['date']} الساعة {e['time']} ({e['session']})" for e in EXAMS])

    # Try Gemini on-demand
    if GEMINI_KEY:
        prompt = f"""أنت مساعد ذكي لموقع أكاديمي لقسم جامعي. أجب بالعربية فقط وبشكل مختصر ومفيد.

معلومات الموقع:
المواد الدراسية:
{subj_list}

جدول الامتحانات:
{exams_list}

الموقع فيه ملفات Cours, TD, TP, Summary لكل مادة.

سؤال الطالب: {orig}

أجب بشكل طبيعي ومختصر (جملتين لأربع جمل). إذا سأل عن شرح أو تلخيص، قدم شرح مختصر مفيد."""
        endpoints = ["v1", "v1beta"]
        models = ["gemini-2.0-flash", "gemini-1.5-flash"]
        reply = None
        for ep in endpoints:
            for model in models:
                try:
                    data = json.dumps({"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"maxOutputTokens":400,"temperature":0.7}}).encode()
                    url = f"https://generativelanguage.googleapis.com/{ep}/models/{model}:generateContent?key={GEMINI_KEY}"
                    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method="POST")
                    resp = urllib.request.urlopen(req, timeout=15)
                    result = json.loads(resp.read())
                    candidates = result.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                        if text:
                            logger.info(f"Gemini ({model}) OK: {text[:60]}...")
                            return jsonify({"reply": text})
                        else:
                            logger.warning(f"Gemini ({model}) empty text")
                    else:
                        reason = result.get("promptFeedback", {}).get("blockReason", "unknown")
                        logger.warning(f"Gemini ({model}) no candidates, blockReason={reason}")
                except urllib.error.HTTPError as e2:
                    body = e2.read().decode()[:200]
                    logger.warning(f"Gemini ({model}) HTTP {e2.code}: {body}")
                except Exception as e2:
                    logger.warning(f"Gemini ({model}) error: {str(e2)[:200]}")

    # ── Fallback: rule-based ──
    subj_map = {
        "اقتصاد المؤسسة": ["اقتصاد المؤسسة", "مؤسسة", "اقتصاد مؤسسة"],
        "اقتصاد جزئي": ["اقتصاد جزئي", "جزئي", "اقتصاد الجزئي"],
        "الرياضيات 2": ["رياضيات", "رياضيات 2"],
        "الإحصاء 2": ["احصاء", "إحصاء", "إحصاء 2", "احصاء 2", "الإحصاء"],
        "تاريخ الفكر الاقتصادي": ["تاريخ الفكر", "فكر اقتصادي", "تاريخ اقتصادي"],
        "أساسيات البرمجة بايثون 2": ["برمجة", "بايثون", "برمجة بايثون", "أساسيات البرمجة"],
        "المحاسبة المالية 2": ["محاسبة", "محاسبة مالية", "محاسبة 2"],
        "المصطلحات الاقتصادية بالإنجليزية": ["مصطلحات", "مصطلحات اقتصادية", "إنجليزية", "انجليزية", "انجليزي"],
        "القانون التجاري": ["قانون", "قانون تجاري", "تجاري"],
    }
    cat_map = {"cours": "Cours", "td": "TD", "tp": "TP", "summary": "Summary", "ملخص": "Summary", "كورس": "Cours"}
    days_ar = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]

    found_subject = None
    for full_name, keywords in subj_map.items():
        if any(k in msg_lower for k in keywords):
            found_subject = full_name
            break

    found_cat = None
    for kw, cat in cat_map.items():
        if kw in msg_lower:
            found_cat = cat
            break

    if any(w in msg_lower for w in ["مرحبا", "السلام", "اهلا", "أهلا", "صباح الخير", "مساء الخير", "hi", "hello"]):
        return jsonify({"reply": "مرحباً بك في بورتال القسم! 😊\n\nأسئلة أقدر أساعدك فيها:\n• أين ملفات مادة معينة؟\n• متى امتحان مادة؟\n• كيف أستخدم الموقع؟\n\nاكتب سؤالك 👇"})

    if any(w in msg_lower for w in ["شكرا", "شكراً", "تسلم", "thanks"]):
        return jsonify({"reply": "العفو! دائمًا في الخدمة 🤍"})

    if any(w in msg_lower for w in ["امتحان", "جدول", "موعد", "متى"]):
        if found_subject:
            for e in EXAMS:
                if e["subject"] == found_subject or found_subject in e["subject"]:
                    d = datetime.strptime(e["date"], "%Y-%m-%d")
                    return jsonify({"reply": f"📅 امتحان {e['subject']}:\n📆 {days_ar[d.weekday()]} {d.day} {'يناير فبراير مارس أبريل ماي يونيو يوليو أغسطس سبتمبر أكتوبر نوفمبر ديسمبر'.split()[d.month-1]} {d.year}\n⏰ {e['time']}\n🌅 {e['session']}"})
        exams_txt = "\n\n".join([f"📅 {e['subject']}: {e['date']} الساعة {e['time']} ({e['session']})" for e in EXAMS])
        return jsonify({"reply": f"📋 جدول الامتحانات النهائية:\n\n{exams_txt}"})

    if found_subject:
        files_data = get_files_by_subject()
        subj_files = files_data.get(found_subject)
        if subj_files:
            available = []
            for cat in CATEGORIES:
                items = subj_files.get(cat, [])
                if not found_cat or found_cat == cat:
                    if items:
                        available.append(f"📂 {cat}: {len(items)} ملف")
                        for x in items[:3]:
                            available.append(f"  • {x['original'][:40]}")
                        if len(items) > 3:
                            available.append(f"  ... و{len(items)-3} ملفات أخرى")
            if available:
                reply = f"📚 ملفات {found_subject}:\n" + "\n".join(available)
                reply += "\n\n📌 افتح المادة من الصفحة الرئيسية عشان تشوف الكل"
                return jsonify({"reply": reply})

    if any(w in msg_lower for w in ["الملفات", "المواد"]):
        subjects_list = "\n".join([f"  {i+1}. {s}" for i, s in enumerate(SUBJECTS)])
        return jsonify({"reply": f"📁 المواد الدراسية المتوفرة:\n{subjects_list}\n\nاكتب اسم المادة عشان تشوف ملفاتها"})

    if any(w in msg_lower for w in ["كيف", "وين", "أين", "استخدام", "ايش", "وش", "شنو", "ماذا", "help"]):
        return jsonify({"reply": "🤖 كيف أستخدم البورتال:\n\n1. ابحث عن مادة (🔍)\n2. اضغط على المادة عشان تشوف ملفاتها\n3. في المودال تقدر تشوف، تحمل، أو تنسخ رابط الملف\n4. استخدم زر الألوان 🎨 عشان تغير شكل الموقع\n5. زر 🌙 عشان تظلم/تضيء الموقع"})

    if GEMINI_KEY:
        return jsonify({"reply": "💡 اسألني عن المواد، الامتحانات، أو اطلب مني أشرح لك أي شيء!"})
    return jsonify({"reply": "🤔 ما فهمت سؤالك. جرب:\n\n• 'وين ملفات الرياضيات؟'\n• 'متى امتحان القانون؟'\n• 'شو المواد الموجودة؟'\n• 'كيف أستخدم الموقع؟'"})


@app.route("/webhook", methods=["POST"])
def webhook():
    if not bot:
        return "", 503
    if request.headers.get("content-type") != "application/json":
        return "", 403
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "", 200


@app.route("/api/gemini-status")
def gemini_status():
    key_preview = GEMINI_KEY[:15] + "..." if GEMINI_KEY else None
    return jsonify({"key_set": bool(GEMINI_KEY), "key_preview": key_preview})


@app.route("/api/download/<int:file_id>", methods=["POST"])
def api_download(file_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE files SET downloads = COALESCE(downloads, 0) + 1 WHERE id = %s RETURNING downloads", (file_id,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    return jsonify({"downloads": row["downloads"] if row else 0})


if __name__ == "__main__":
    try:
        init_db()
        migrate_old_urls()
    except Exception as e:
        logger.error(f"init_db failed: {e}")
        raise
    port = int(os.getenv("PORT", 5000))
    if bot and ADMIN_ID:
        webhook_url = (os.getenv("RENDER_EXTERNAL_URL") or f"http://localhost:{port}").rstrip("/")
        full = f"{webhook_url}/webhook"
        try:
            bot.remove_webhook()
            bot.set_webhook(url=full)
            logger.info(f"Webhook set to {full}")
        except Exception as e:
            logger.error(f"Webhook setup failed: {e}")
    app.run(debug=False, port=port, host="0.0.0.0")
