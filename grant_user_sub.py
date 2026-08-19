"""
TelePilot SaaS - Manual Subscription Verification & Grant Tool
Usage:
  python grant_user_sub.py <telegram_id_or_username> [days]

Examples:
  python grant_user_sub.py @laily 30
  python grant_user_sub.py 123456789 30
"""

import sys
import sqlite3
from datetime import datetime, timedelta

def grant_subscription_sqlite(user_input: str, days: int = 30):
    conn = sqlite3.connect('telegram_saas.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    clean_target = user_input.lstrip('@').strip()

    # Find user by ID or username
    user = None
    if clean_target.isdigit():
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (int(clean_target),))
        user = cursor.fetchone()
    
    if not user:
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(full_name) LIKE LOWER(?)", (clean_target, f"%{clean_target}%"))
        user = cursor.fetchone()

    if not user:
        print(f"❌ User '{user_input}' not found in database.")
        print("\nListing recent registered users:")
        cursor.execute("SELECT id, telegram_id, username, full_name, created_at FROM users ORDER BY id DESC LIMIT 15")
        for r in cursor.fetchall():
            print(dict(r))
        conn.close()
        return False

    user_id = user['id']
    tg_id = user['telegram_id']
    username = user['username'] or user['full_name'] or str(tg_id)

    now = datetime.utcnow()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S.%f')
    
    cursor.execute("SELECT * FROM subscriptions WHERE user_id = ? AND status = 'ACTIVE' AND expires_at > ? ORDER BY expires_at DESC LIMIT 1", (user_id, now_str))
    active_sub = cursor.fetchone()

    plan_name = f"{days} Days Plan"
    if active_sub:
        curr_exp = datetime.strptime(active_sub['expires_at'].split('.')[0], '%Y-%m-%d %H:%M:%S')
        new_exp = max(now, curr_exp) + timedelta(days=days)
        new_exp_str = new_exp.strftime('%Y-%m-%d %H:%M:%S.%f')
        cursor.execute("UPDATE subscriptions SET expires_at = ?, plan_name = ? WHERE id = ?", (new_exp_str, plan_name, active_sub['id']))
        print(f"✅ Subscription extended for user @{username} (Telegram ID: {tg_id})")
        print(f"   Previous Expiry: {curr_exp}")
        print(f"   New Expiry: {new_exp}")
    else:
        new_exp = now + timedelta(days=days)
        new_exp_str = new_exp.strftime('%Y-%m-%d %H:%M:%S.%f')
        cursor.execute(
            "INSERT INTO subscriptions (user_id, plan_name, max_accounts, status, expires_at, created_at) VALUES (?, ?, 5, 'ACTIVE', ?, ?)",
            (user_id, plan_name, new_exp_str, now_str)
        )
        print(f"✅ New {days}-Day Subscription activated for user @{username} (Telegram ID: {tg_id})")
        print(f"   Active Until: {new_exp.strftime('%d %b %Y, %I:%M %p UTC')}")

    # Mark any pending payment for user as VERIFIED
    cursor.execute("UPDATE payments SET status = 'VERIFIED' WHERE user_id = ? AND status = 'PENDING'", (user_id,))
    
    conn.commit()
    conn.close()
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python grant_user_sub.py <username_or_telegram_id> [days]")
        print("Example: python grant_user_sub.py @laily 30")
        sys.exit(1)

    target_user = sys.argv[1]
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    grant_subscription_sqlite(target_user, duration)
