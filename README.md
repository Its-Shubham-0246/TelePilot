# Telegram SaaS Multi-Account Automation Platform

A subscription-based Telegram automation SaaS platform powered by **Telethon** (MTProto API), **Aiogram 3** (Bot UI), **FastAPI** (REST Backend API), **SQLAlchemy 2.0** (Async Database), **Redis**, and **APScheduler**.

---

## 🚀 Features

- **Interactive Bot Interface**: Complete bot menu navigation (`🏠 Dashboard`, `➕ Add Account`, `👤 My Accounts`, `💬 Messages`, `⏰ Scheduler`, `▶️ Start`, `⏸ Pause`, `⏹ Stop`, `📊 Status`, `💳 Subscription`, `⚙️ Settings`, `🆘 Support`).
- **Secure MTProto Multi-Account Sign-in**:
  - Max 15 connected accounts per user.
  - Interactive FSM sign-in (Phone -> OTP Code -> 2FA Password).
  - **AES-256 Fernet Encryption** for stored StringSession tokens at rest.
  - Zero OTP retention (handled exclusively in transient memory).
- **Anti-Spam & Rate Limit Protection**:
  - Message variant rotation (spin syntax support).
  - Jitter delays (1-5 seconds random offset).
  - Automatic `FloodWait` detection and account health status tracking (`ACTIVE`, `FLOOD_WAIT`, `BANNED`, `RE_LOGIN_REQUIRED`).
- **Scheduling Engine**:
  - Auto Group, Auto DM, or Combined mode dispatches.
  - Custom interval in minutes and daily active hour windows.
  - Auto-pauses schedules if subscription expires.
- **SaaS Subscription & Payments**:
  - Plans: 30 Days (₹299), 90 Days (₹699), 180 Days (₹1,199), 365 Days (₹1,999).
  - Instant payment verification callback system & webhook integration.
- **Admin Control Panel**:
  - Bot command `/admin` & REST API endpoints.
  - User metrics, revenue tracking, user ban/unban toggles, and global announcements.

---

## 🛠 Project Architecture

```
e:\telegram_bot
├── config.py                 # Pydantic environment configuration
├── main.py                   # Entry point (Bot + FastAPI + Scheduler)
├── core/
│   ├── database.py           # Async SQLAlchemy engine & session factory
│   └── security.py           # AES-256 Fernet session token encryption
├── models/                   # Database models (User, Sub, Account, Template, Schedule, JobLog, Payment)
├── services/
│   ├── mtproto_service.py    # Telethon MTProto client manager
│   ├── subscription_service.py # Plan duration & pricing calculations
│   └── scheduler_service.py # APScheduler background job dispatcher
├── bot/
│   ├── bot_instance.py       # Aiogram Bot & Dispatcher instances
│   ├── keyboards/            # Reply & Inline Keyboard Markups
│   └── handlers/             # Command & Menu Event Handlers
├── api/                      # FastAPI Backend Routes (/health, /admin, /payments)
├── tests/                    # Pytest test suite
├── Dockerfile & docker-compose.yml
└── requirements.txt
```

---

## ⚡ Quick Start

### 1. Environment Configuration
Copy `.env.example` to `.env` and provide your credentials:

```bash
BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
ENCRYPTION_SECRET_KEY=uY72wN-xP_0q20Kz_T_G-8w1F0Y-L5Z1vX9W3R7y5tM=
```

### 2. Running Locally with Python
```bash
pip install -r requirements.txt
python main.py
```

### 3. Running with Docker Compose
```bash
docker-compose up -d --build
```

---

## 🧪 Testing

Run pytest to execute the test suite:
```bash
pytest
```

---

## 🚂 Deploying to Railway

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<YOUR_USERNAME>/<YOUR_REPO>.git
git push -u origin main
```

### Step 2 — Create Railway Project
1. Go to [railway.app](https://railway.app) and sign in
2. Click **New Project → Deploy from GitHub Repo**
3. Select your repository

### Step 3 — Add PostgreSQL & Redis
1. In your Railway project, click **+ New** → **Database** → **Add PostgreSQL**
2. Click **+ New** → **Database** → **Add Redis**
3. Railway auto-sets `DATABASE_URL` and `REDIS_URL` in your service

### Step 4 — Set Environment Variables
In your Railway service → **Variables** tab, add:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Your BotFather token |
| `TELEGRAM_API_ID` | Your Telegram API ID |
| `TELEGRAM_API_HASH` | Your Telegram API Hash |
| `ENCRYPTION_SECRET_KEY` | Your Fernet key |
| `ADMIN_TELEGRAM_IDS` | Your Telegram user ID |
| `RAZORPAY_KEY_ID` | Your Razorpay key |
| `RAZORPAY_KEY_SECRET` | Your Razorpay secret |
| `RAZORPAY_WEBHOOK_SECRET` | Your webhook secret |

> `DATABASE_URL`, `REDIS_URL`, and `PORT` are auto-injected by Railway — do not set them manually.

### Step 5 — Deploy
Railway auto-deploys on every `git push`. Monitor logs in the Railway dashboard.

### Step 6 — Verify
- Check Railway logs for `Starting Telegram SaaS System...`
- Hit `https://<your-app>.railway.app/health` → should return `{"status": "ok"}`
- Send `/start` to your bot on Telegram
