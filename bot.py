#!/usr/bin/env python3
"""
MymokiBot - Personal Assistant Telegram Bot
תומך בתזכורות קבועות ודינמיות, ניהול לוח זמנים
"""

import os
import json
import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, JobQueue
)

# ─── הגדרות ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_CHAT_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))

MORNING_HOUR = 7
MORNING_MINUTE = 0
EVENING_HOUR = 20
EVENING_MINUTE = 0

DATA_FILE = Path("schedules.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── שמירת נתונים ─────────────────────────────────────────
def load_data() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"events": []}

def save_data(data: dict):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def add_event(title: str, dt: datetime) -> dict:
    data = load_data()
    event = {
        "id": int(datetime.now().timestamp() * 1000),
        "title": title,
        "datetime": dt.isoformat(),
        "reminded_60": False,
        "reminded_30": False,
    }
    data["events"].append(event)
    save_data(data)
    return event

def get_events_for_day(day: datetime) -> list:
    data = load_data()
    result = []
    for e in data["events"]:
        try:
            edt = datetime.fromisoformat(e["datetime"])
            if edt.date() == day.date():
                result.append(e)
        except Exception:
            pass
    return sorted(result, key=lambda x: x["datetime"])

def delete_event(event_id: int) -> bool:
    data = load_data()
    before = len(data["events"])
    data["events"] = [e for e in data["events"] if e["id"] != event_id]
    save_data(data)
    return len(data["events"]) < before

# ─── פרסור תאריך/שעה בעברית ──────────────────────────────
DAYS_HE = {
    "ראשון": 6, "שני": 0, "שלישי": 1, "רביעי": 2,
    "חמישי": 3, "שישי": 4, "שבת": 5,
    "sunday": 6, "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5,
}

def parse_datetime(text: str) -> datetime | None:
    now = datetime.now()
    text = text.strip()

    # חפש שעה בפורמט 13:00 או 13
    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?", text)
    hour = int(time_match.group(1)) if time_match else None
    minute = int(time_match.group(2)) if time_match and time_match.group(2) else 0

    # חפש יום
    target_date = None

    if "היום" in text or "today" in text.lower():
        target_date = now.date()
    elif "מחר" in text or "tomorrow" in text.lower():
        target_date = (now + timedelta(days=1)).date()
    else:
        for day_name, weekday in DAYS_HE.items():
            if day_name in text.lower():
                days_ahead = (weekday - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                target_date = (now + timedelta(days=days_ahead)).date()
                break

    if target_date is None:
        # חפש תאריך בפורמט DD/MM
        date_match = re.search(r"(\d{1,2})/(\d{1,2})", text)
        if date_match:
            day_num = int(date_match.group(1))
            month_num = int(date_match.group(2))
            year = now.year
            try:
                target_date = datetime(year, month_num, day_num).date()
                if target_date < now.date():
                    target_date = datetime(year + 1, month_num, day_num).date()
            except ValueError:
                return None
        else:
            target_date = now.date()

    if hour is None:
        return None

    try:
        return datetime(target_date.year, target_date.month, target_date.day, hour, minute)
    except ValueError:
        return None

def extract_event_title(text: str) -> str:
    """מחלץ את כותרת האירוע מהטקסט"""
    # הסר מילות פקודה נפוצות
    for prefix in ["תזכיר לי", "תזכור לי", "הוסף", "עבודה אצל", "פגישה עם", "לדבר עם", "זמן עם"]:
        text = text.replace(prefix, "").strip()
    # הסר ביטויי זמן
    text = re.sub(r"\b(היום|מחר|ב|ביום|בשעה)\b", "", text)
    text = re.sub(r"\d{1,2}(:\d{2})?", "", text)
    text = re.sub(r"\b(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else "אירוע"

# ─── מקלדת ────────────────────────────────────────────────
def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📅 מה יש לי היום?"), KeyboardButton("📆 מה יש לי השבוע?")],
        [KeyboardButton("➕ הוסף אירוע"), KeyboardButton("🗑️ מחק אירוע")],
        [KeyboardButton("ℹ️ עזרה")],
    ], resize_keyboard=True)

# ─── handlers ─────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 שלום! אני *עוזר אישי* שלך.\n\n"
        "אני יכול:\n"
        "• לשלוח לך תזכורות בוקר וערב 🌅🌙\n"
        "• להזכיר לך על עבודות ופגישות ⏰\n"
        "• לנהל את הלוח שלך 📅\n\n"
        "פשוט כתוב לי משהו כמו:\n"
        "_תזכיר לי לדבר עם רונית ביום חמישי ב-13:00_\n"
        "_עבודה אצל כהנים ביום שישי ב-8:00_",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    # שמור את ה-chat_id
    if OWNER_CHAT_ID == 0:
        chat_id = update.effective_chat.id
        log.info(f"First user chat_id: {chat_id}")
        env_path = Path(".env")
        if env_path.exists():
            content = env_path.read_text()
            if "OWNER_CHAT_ID" not in content:
                env_path.write_text(content + f"\nOWNER_CHAT_ID={chat_id}\n")

async def show_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    events = get_events_for_day(datetime.now())
    if not events:
        await update.message.reply_text("✅ אין אירועים מיוחדים היום.", reply_markup=main_keyboard())
        return
    lines = ["📅 *האירועים של היום:*\n"]
    for e in events:
        dt = datetime.fromisoformat(e["datetime"])
        lines.append(f"• {dt.strftime('%H:%M')} — {e['title']} (ID: `{e['id']}`)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())

async def show_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["📆 *האירועים השבוע:*\n"]
    found = False
    day_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    for i in range(7):
        day = datetime.now() + timedelta(days=i)
        events = get_events_for_day(day)
        if events:
            found = True
            dow = day_names[day.weekday()]
            lines.append(f"*יום {dow} {day.strftime('%d/%m')}:*")
            for e in events:
                dt = datetime.fromisoformat(e["datetime"])
                lines.append(f"  • {dt.strftime('%H:%M')} — {e['title']}")
            lines.append("")
    if not found:
        lines.append("אין אירועים השבוע ✅")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # כפתורים
    if "מה יש לי היום" in text:
        return await show_today(update, ctx)
    if "מה יש לי השבוע" in text:
        return await show_week(update, ctx)
    if "עזרה" in text or "help" in text.lower():
        return await cmd_help(update, ctx)
    if "מחק אירוע" in text or "הוסף אירוע" in text:
        await update.message.reply_text(
            "כתוב לי:\n"
            "• *להוסיף:* `תזכיר לי [מה] [מתי]`\n"
            "  לדוגמא: _תזכיר לי לדבר עם רונית ביום חמישי ב-13:00_\n\n"
            "• *למחוק:* `מחק [ID]`\n"
            "  (ה-ID מופיע ליד האירוע כשאתה רואה את הרשימה)",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return

    # מחיקה
    delete_match = re.match(r"מחק\s+(\d+)", text)
    if delete_match:
        eid = int(delete_match.group(1))
        if delete_event(eid):
            await update.message.reply_text("🗑️ האירוע נמחק!", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("לא מצאתי אירוע עם המספר הזה.", reply_markup=main_keyboard())
        return

    # זיהוי תזכורת / אירוע
    trigger_words = ["תזכיר", "תזכור", "עבודה", "פגישה", "לדבר עם", "זמן עם", "להיפגש", "אצל"]
    is_event = any(w in text for w in trigger_words)

    if is_event:
        dt = parse_datetime(text)
        if dt:
            title = extract_event_title(text)
            if not title or len(title) < 2:
                # נסה להשתמש בחלק מהטקסט המקורי
                title = text[:50]
            event = add_event(title, dt)
            day_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
            dow = day_names[dt.weekday()]
            await update.message.reply_text(
                f"✅ *נשמר!*\n\n"
                f"📌 {title}\n"
                f"📅 יום {dow} {dt.strftime('%d/%m')} בשעה {dt.strftime('%H:%M')}\n\n"
                f"אזכיר לך שעה ו-30 דקות לפני.",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        else:
            await update.message.reply_text(
                "🤔 לא הצלחתי להבין את השעה/תאריך.\n"
                "נסה כך: _תזכיר לי לדבר עם רונית ביום חמישי ב-13:00_",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
    else:
        await update.message.reply_text(
            "לא הבנתי 😅\n\nנסה:\n"
            "• _תזכיר לי [מה] ביום [יום] ב-[שעה]_\n"
            "• _מה יש לי היום?_\n"
            "• _מה יש לי השבוע?_",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *פקודות שאני מבין:*\n\n"
        "🔔 *תזכורות:*\n"
        "• `תזכיר לי לדבר עם רונית ביום חמישי ב-13:00`\n"
        "• `עבודה אצל כהנים ביום שישי ב-8`\n"
        "• `פגישה עם דני מחר ב-10:30`\n\n"
        "📅 *לוח זמנים:*\n"
        "• `מה יש לי היום?`\n"
        "• `מה יש לי השבוע?`\n\n"
        "🗑️ *מחיקה:*\n"
        "• `מחק [מספר ID]`\n\n"
        "⏰ *תזכורות קבועות אוטומטיות:*\n"
        "• 7:00 — קריאטין + מים 💊\n"
        "• 20:00 — לקרוא מהספר 📚",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

# ─── תזכורות אוטומטיות ────────────────────────────────────
async def morning_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    if OWNER_CHAT_ID == 0:
        return
    await ctx.bot.send_message(
        chat_id=OWNER_CHAT_ID,
        text="☀️ *בוקר טוב!*\n\n"
             "💊 אל תשכח לקחת *קריאטין* ולשתות כוס *מים* גדולה!\n\n"
             "יום מוצלח 💪",
        parse_mode="Markdown"
    )

async def evening_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    if OWNER_CHAT_ID == 0:
        return
    await ctx.bot.send_message(
        chat_id=OWNER_CHAT_ID,
        text="🌙 *ערב טוב!*\n\n"
             "📚 זמן לקרוא כמה עמודים מהספר!\n"
             "כמה דקות של קריאה לפני השינה עושות פלאים 😊",
        parse_mode="Markdown"
    )

async def check_upcoming_events(ctx: ContextTypes.DEFAULT_TYPE):
    """רץ כל דקה ובודק אם יש אירועים קרובים"""
    if OWNER_CHAT_ID == 0:
        return
    now = datetime.now()
    data = load_data()
    changed = False

    for event in data["events"]:
        try:
            edt = datetime.fromisoformat(event["datetime"])
            diff_minutes = (edt - now).total_seconds() / 60

            # תזכורת שעה לפני
            if 58 <= diff_minutes <= 62 and not event.get("reminded_60"):
                await ctx.bot.send_message(
                    chat_id=OWNER_CHAT_ID,
                    text=f"⏰ *תזכורת — עוד שעה!*\n\n📌 {event['title']}\n🕐 {edt.strftime('%H:%M')}",
                    parse_mode="Markdown"
                )
                event["reminded_60"] = True
                changed = True

            # תזכורת 30 דקות לפני
            if 28 <= diff_minutes <= 32 and not event.get("reminded_30"):
                await ctx.bot.send_message(
                    chat_id=OWNER_CHAT_ID,
                    text=f"⏰ *תזכורת — עוד 30 דקות!*\n\n📌 {event['title']}\n🕐 {edt.strftime('%H:%M')}",
                    parse_mode="Markdown"
                )
                event["reminded_30"] = True
                changed = True

        except Exception as e:
            log.error(f"Error checking event: {e}")

    if changed:
        save_data(data)

# ─── הרצת הבוט ────────────────────────────────────────────
def main():
    token = BOT_TOKEN
    if not token:
        raise ValueError("BOT_TOKEN is not set!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", show_today))
    app.add_handler(CommandHandler("week", show_week))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    jq: JobQueue = app.job_queue

    # תזכורת בוקר 7:00
    jq.run_daily(morning_reminder, time=datetime.now().replace(
        hour=MORNING_HOUR, minute=MORNING_MINUTE, second=0, microsecond=0
    ).time())

    # תזכורת ערב 20:00
    jq.run_daily(evening_reminder, time=datetime.now().replace(
        hour=EVENING_HOUR, minute=EVENING_MINUTE, second=0, microsecond=0
    ).time())

    # בדיקת אירועים קרובים — כל דקה
    jq.run_repeating(check_upcoming_events, interval=60, first=10)

    log.info("🤖 MymokiBot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
