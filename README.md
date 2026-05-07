# Section 2 - Groupe 12 | Content Management Portal

A web app + Telegram bot for managing academic content (Lectures, TD, TP, Summaries).

## Project Structure

```
section2-group12-portal/
├── index.py                   # Flask server + Telegram bot (main entry point)
├── requirements.txt           # Python dependencies
├── .env                       # Your bot token & admin ID (edit this!)
├── .env.example               # Template for .env
├── README.md                  # This file
├── templates/
│   └── index.html             # Frontend dashboard
└── uploads/                   # Uploaded files (auto-created)
    ├── اقتصاد المؤسسة/
    ├── الاقتصاد الجزئي 2/
    ├── الرياضيات 2/
    ├── الإحصاء 2/
    ├── تاريخ الفكر الاقتصادي/
    ├── أساسيات البرمجة بايثون 2/
    ├── المحاسبة المالية 2/
    ├── المصطلحات الاقتصادية بالإنجليزية/
    └── القانون التجاري/
```

## Setup Instructions

### 1. Install Python 3.8+

Make sure Python 3.8+ is installed on your system:
```bash
python --version
```

### 2. Install Dependencies

Open a terminal in the project folder and run:
```bash
pip install -r requirements.txt
```

### 3. Get Your Telegram Bot Token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts to create a new bot
3. Copy the API token (looks like `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 4. Get Your Telegram User ID

1. Search for **@userinfobot** on Telegram
2. Send `/start` — it will reply with your numeric ID

### 5. Configure the .env File

Edit the `.env` file in the project folder:
```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_ID=123456789
```

Replace the values with your actual bot token and Telegram user ID.

### 6. Run the Application

```bash
python index.py
```

You should see:
```
Bot polling started in background thread.
Flask server running at http://127.0.0.1:5000
```

### 7. Access the Website

Open your browser and go to: **http://127.0.0.1:5000**

## How to Use the Telegram Bot

1. Open your bot on Telegram
2. Send `/start` — you'll see a menu of all 8 subjects
3. Click a subject to select it
4. Choose a category (Cours, TD, TP, or Summary)
5. Send a PDF file or image
6. The bot confirms the upload — the file is now visible on the website!

## How to Use the Website

- Open http://127.0.0.1:5000 in your browser
- Click any subject card to open its file browser
- Files are organized by category (Cours, TD, TP, Summary)
- Click the eye icon to view a file
- Click the download icon to download a file

## Notes

- The bot only responds to your Telegram ID (as set in ADMIN_ID)
- All files are stored locally in the `uploads/` folder
- The database (`database.db`) is created automatically when you run the app
- The website updates in real-time — just refresh the page after uploading
