import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiohttp import web

# Tokenni Render muhitidan yoki to'g'ridan-to'g'ri yozib olamiz
TOKEN = os.getenv("BOT_TOKEN", "SIZNING_BOT_TOKENINGIZNI_SHU_YERGA_YOZING")
GROUP_ID = int(os.getenv("GROUP_ID", "-100xxxxxxxxxx")) # Guruhigiz ID raqami

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- BAZA BILAN ISHLASH ---
def init_db():
    conn = sqlite3.connect("group_stats.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_at TEXT,
            last_active TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- GURUHNI KUZATISH ---
@dp.message(F.chat.type.in_({ "group", "supergroup" }))
async def monitor_group(message: types.Message):
    conn = sqlite3.connect("group_stats.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")

    if message.new_chat_members:
        for user in message.new_chat_members:
            if user.is_bot: continue
            cursor.execute("""
                INSERT OR REPLACE INTO users (user_id, username, full_name, joined_at, last_active)
                VALUES (?, ?, ?, ?, ?)
            """, (user.id, user.username, user.full_name, now, now))
            cursor.execute("INSERT INTO activity_log (user_id, action, date) VALUES (?, 'joined', ?)", (user.id, today))
        conn.commit()

    if message.left_chat_member:
        user = message.left_chat_member
        if not user.is_bot:
            cursor.execute("INSERT INTO activity_log (user_id, action, date) VALUES (?, 'left', ?)", (user.id, today))
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user.id,))
        conn.commit()

    if message.from_user and not message.from_user.is_bot:
        user = message.from_user
        cursor.execute("""
            INSERT OR REPLACE INTO users (user_id, username, full_name, joined_at, last_active)
            VALUES (?, ?, ?, COALESCE((SELECT joined_at FROM users WHERE user_id = ?), ?), ?)
        """, (user.id, user.username, user.full_name, user.id, now, now))
        cursor.execute("INSERT INTO activity_log (user_id, action, date) VALUES (?, 'message', ?)", (user.id, today))
        conn.commit()

    conn.close()

# --- KUNLIK HISOBOT ---
async def daily_report_task():
    while True:
        now = datetime.now()
        target = now.replace(hour=23, minute=59, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

        conn = sqlite3.connect("group_stats.db")
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")

        cursor.execute("SELECT COUNT(*) FROM activity_log WHERE action='joined' AND date=?", (today,))
        joined_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM activity_log WHERE action='left' AND date=?", (today,))
        left_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT u.full_name, COUNT(a.id) as msg_count 
            FROM activity_log a JOIN users u ON a.user_id = u.user_id 
            WHERE a.action='message' AND a.date=? 
            GROUP BY a.user_id ORDER BY msg_count DESC LIMIT 5
        """, (today,))
        top_active = cursor.fetchall()

        three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("SELECT full_name FROM users WHERE last_active < ?", (three_days_ago,))
        inactive_users = cursor.fetchall()
        conn.close()

        report = (
            f"📊 **Guruhning Kunlik Statistikasi ({today})**\n\n"
            f"🟢 Qo'shilganlar: **{joined_count}** ta\n"
            f"🔴 Chiqib ketganlar: **{left_count}** ta\n\n"
            f"🔥 **Eng aktiv foydalanuvchilar:**\n"
        )
        for idx, (name, count) in enumerate(top_active, 1):
            report += f"{idx}. {name} — {count} ta xabar\n"

        report += f"\n💤 **Inaktivlar (3 kundan ortiq yozmaganlar):** {len(inactive_users)} ta\n"
        await bot.send_message(GROUP_ID, report, parse_mode="Markdown")

# Render uchun oddiy web server (bot uxlab qolmasligi uchun)
async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    asyncio.create_task(daily_report_task())
    asyncio.create_task(web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
