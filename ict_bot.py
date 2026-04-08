#!/usr/bin/env python3
"""
ICT Trading Telegram Bot
يشتغل على Railway أو Render مجاناً
"""

import os, json, math, logging
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "8780757607:AAFs0Yk5QZUXfsTsbm5JyOP3HpzrdFjxlZY")

# ============ DATA STORE ============
# يُحدَّث يدوياً عبر /update أو تلقائياً
PRICES = {
    "spx": {"price": 6750, "prev": 6617, "high": 6820, "low": 6534, "vix": 25.78},
    "ndx": {"price": 24202, "prev": 24202, "high": 24209, "low": 23779},
    "updated": "لم يُحدَّث بعد"
}

ASTRO_APRIL = {
    8:  [("⚠️ فاصل انتقالي D1/H4", "تصحيح واهتزاز عالٍ — SPX+NDX"),
         ("📉 NDX تصحيح H4", "حركة تصحيح فريم H4")],
    9:  [("⚠️ فاصل انتقالي", "تصحيح واهتزاز عالٍ — استمرار")],
    10: [("✅ BTC ارتداد H1", "دعم وارتداد إيجابي من الفجر إلى 7:00pm")],
    11: [("📉 BTC تقييد H4", "تقييد وتصحيح من الفجر إلى 4:15pm")],
    12: [("✅ اقتران إيجابي", "حركة وهمية — الصميم: 13/4 الساعة 08:29am")],
    13: [("⚠️ الفترة الأهم", "حركة هابطة ضمن الاتجاه الصاعد 13-17/4"),
         ("⚡ BTC مضاربي H1", "الحذر أثناء افتتاح السوق الأمريكي")],
    14: [("⚠️ فاصل انتقالي H4", "تصحيح وتذبذب عالٍ"),
         ("📉 NDX تقييد H4/1H", "ما بعد الإزاحة تقييد")],
    16: [("✅ اقتران سريع ↑", "الصميم: 17/4 الساعة 5:00am")],
    17: [("🔄 نهاية الصاعد ← هابط", "يبدأ الاتجاه الفرعي الهابط"),
         ("✅ BTC ارتداد H1", "من مساء 16/4 إلى 12:30pm")],
    20: [("✅ اقتران تسارع H4", "الصميم: 21/4 الساعة 11:00am"),
         ("🌿 تبدأ الهوية الترابية", "قطاع الأغذية والأدوية والمالية")],
    21: [("✅ BTC ارتداد H4/1D", "إلى 22/4")],
    23: [("⚠️ اقتران + فاصل انتقالي", "تذبذب عالٍ — صاعد يتبعه تصحيح")],
    25: [("✅ BTC ارتداد W1/D1", "زاوية إيجابية تستمر إلى 4/5")],
    26: [("📉 تربيع تقييد ↓", "الصميم: 21:32pm")],
    27: [("🔄 الفترة الأهم الهابط", "حركة صاعدة متوقعة 27-30/4")],
    28: [("✅ SPX+NDX ارتداد H4", "ارتداد على فريم H4")],
    29: [("📉 تربيع تغيير ↓", "الصميم: 30/4 الساعة 4:05am"),
         ("📉 SPX تصحيح H1", "ما بعد الإزاحة")],
}

PENDING_UPDATE = {}  # chat_id -> step

# ============ HELPERS ============
def ksa_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)

def calc_sigma(price, vix):
    edm = price * vix/100 / math.sqrt(252)
    ewm = price * vix/100 / math.sqrt(52)
    emm = price * vix/100 / math.sqrt(12)
    return edm, ewm, emm

def get_session():
    h = ksa_now().hour
    m = ksa_now().minute
    t = h * 60 + m
    if 10*60 <= t < 11*60: return "🟡 Silver Bullet ① (10:00–11:00 KSA)"
    if 11*60 <= t < 13*60: return "🟢 London Open (11:00–13:00 KSA)"
    if 16*60+30 <= t < 18*60+30: return "🟢 NY Open (16:30–18:30 KSA)"
    if 17*60 <= t < 18*60: return "🟡 Silver Bullet ② (17:00–18:00 KSA)"
    if 21*60 <= t < 22*60: return "🟡 Silver Bullet ③ (21:00–22:00 KSA)"
    if 2*60 <= t < 11*60: return "🔵 Asian Session (02:00–11:00 KSA)"
    return "⚪ خارج Killzone"

def format_chg(price, prev):
    chg = price - prev
    pct = chg / prev * 100
    arrow = "📈" if chg >= 0 else "📉"
    sign = "+" if chg >= 0 else ""
    return f"{arrow} {sign}{chg:.1f} ({sign}{pct:.2f}%)"

# ============ COMMANDS ============
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📊 SPX", callback_data="spx"),
         InlineKeyboardButton("📊 NDX", callback_data="ndx")],
        [InlineKeyboardButton("🌙 فلكي اليوم", callback_data="astro"),
         InlineKeyboardButton("🎯 الإشارة", callback_data="signal")],
        [InlineKeyboardButton("✏️ تحديث الأسعار", callback_data="update")],
    ]
    await update.message.reply_text(
        "🤖 *ICT Trading Bot*\n\n"
        "مرحباً! أنا مساعدك اليومي لتحليل SPX وNDX\n\n"
        "اختر أمراً أو استخدم:\n"
        "/spx — تحليل S\\&P 500\n"
        "/ndx — تحليل Nasdaq 100\n"
        "/astro — الفواصل الفلكية اليوم\n"
        "/signal — إشارة اليوم\n"
        "/update — تحديث الأسعار\n"
        "/daily — تقرير يومي شامل",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cmd_spx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    d = PRICES["spx"]
    vix = d["vix"]
    edm, ewm, emm = calc_sigma(d["price"], vix)
    chg_txt = format_chg(d["price"], d["prev"])

    text = (
        f"📊 *SPX — S\\&P 500*\n"
        f"🕐 {ksa_now().strftime('%H:%M')} KSA\n\n"
        f"💰 *السعر:* `{d['price']:,.0f}`\n"
        f"{chg_txt}\n"
        f"📈 High: `{d['high']:,.0f}` | 📉 Low: `{d['low']:,.0f}`\n"
        f"⚡ VIX: `{vix}`\n\n"
        f"🗺️ *مناطق السيولة:*\n"
        f"🔵 BSL: `{d['high']:,.0f}` ← High اليوم\n"
        f"📍 الحالي: `{d['price']:,.0f}`\n"
        f"🔴 SSL: `{d['low']:,.0f}` ← Low اليوم\n\n"
        f"📐 *الانحراف المعياري:*\n"
        f"±1σ يومي: `{d['price']-edm:,.0f}` – `{d['price']+edm:,.0f}`\n"
        f"±1σ أسبوعي: `{d['price']-ewm:,.0f}` – `{d['price']+ewm:,.0f}`\n"
        f"±1σ شهري: `{d['price']-emm:,.0f}` – `{d['price']+emm:,.0f}`\n\n"
        f"🎯 *الإشارة:* 📉 PUT\n"
        f"دخول: `6,750–6,820` | SL: `6,860`\n"
        f"TP1: `6,640` | TP2: `6,534`\n\n"
        f"⚠️ للأغراض التعليمية فقط"
    )
    await msg.reply_text(text, parse_mode="Markdown")

async def cmd_ndx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    d = PRICES["ndx"]
    vix = PRICES["spx"]["vix"]
    edm, ewm, emm = calc_sigma(d["price"], vix)
    chg_txt = format_chg(d["price"], d["prev"])

    text = (
        f"📊 *NDX — Nasdaq 100*\n"
        f"🕐 {ksa_now().strftime('%H:%M')} KSA\n\n"
        f"💰 *السعر:* `{d['price']:,.0f}`\n"
        f"{chg_txt}\n"
        f"📈 High: `{d['high']:,.0f}` | 📉 Low: `{d['low']:,.0f}`\n"
        f"⚡ VIX: `{vix}`\n\n"
        f"🗺️ *مناطق السيولة:*\n"
        f"🔵 BSL: `{d['high']:,.0f}` ← High اليوم\n"
        f"📍 الحالي: `{d['price']:,.0f}`\n"
        f"🔴 SSL: `{d['low']:,.0f}` ← Low اليوم\n\n"
        f"📐 *الانحراف المعياري:*\n"
        f"±1σ يومي: `{d['price']-edm:,.0f}` – `{d['price']+edm:,.0f}`\n"
        f"±1σ أسبوعي: `{d['price']-ewm:,.0f}` – `{d['price']+ewm:,.0f}`\n"
        f"±1σ شهري: `{d['price']-emm:,.0f}` – `{d['price']+emm:,.0f}`\n\n"
        f"🎯 *الإشارة:* 📉 PUT\n"
        f"دخول: `24,200–24,500` | SL: `24,700`\n"
        f"TP1: `23,779` | TP2: `23,410`\n\n"
        f"⚠️ للأغراض التعليمية فقط"
    )
    await msg.reply_text(text, parse_mode="Markdown")

async def cmd_astro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    day = ksa_now().day
    month = ksa_now().month
    evs = ASTRO_APRIL.get(day, []) if month == 4 else []

    # Trend
    if 2 <= day < 17:
        trend = f"📈 *الاتجاه الفرعي الصاعد* (2/4–17/4)\nمتبقي: {17-day} يوم"
        if 13 <= day <= 17:
            trend += "\n⚠️ *الفترة الحرجة — حركة هابطة متوقعة*"
    elif 17 <= day <= 30:
        trend = f"📉 *الاتجاه الفرعي الهابط* (17/4–1/5)\nمتبقي: {30-day} يوم"
        if 27 <= day <= 30:
            trend += "\n⚠️ *الفترة الحرجة — حركة صاعدة متوقعة*"
    else:
        trend = "—"

    identity = "🔥 هوية نارية — تذبذب عالٍ" if day < 20 else "🌿 هوية ترابية — تذبذب بطيء"

    evs_txt = "\n".join([f"• {e[0]}: {e[1]}" for e in evs]) if evs else "لا توجد فواصل خاصة اليوم"

    text = (
        f"🌙 *الفواصل الفلكية — {day} أبريل 2026*\n"
        f"by Zaina Astro\n\n"
        f"{trend}\n\n"
        f"🌟 *الهوية الزمنية:*\n{identity}\n\n"
        f"📅 *فواصل اليوم:*\n{evs_txt}\n\n"
        f"⏰ *الجلسة الحالية:*\n{get_session()}"
    )
    await msg.reply_text(text, parse_mode="Markdown")

async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    d = PRICES["spx"]
    text = (
        f"🎯 *إشارة اليوم — {ksa_now().strftime('%d/%m/%Y')}*\n\n"
        f"📊 *SPX — S\\&P 500*\n"
        f"الإشارة: 📉 *PUT*\n"
        f"الثقة: 72%\n"
        f"الدخول: `6,750 – 6,820`\n"
        f"SL: `6,860`\n"
        f"TP1: `6,640` \\(RR 1:2.2\\)\n"
        f"TP2: `6,534` \\(RR 1:3.9\\)\n"
        f"TP3: `6,421` \\(RR 1:5.9\\)\n\n"
        f"📊 *NDX — Nasdaq 100*\n"
        f"الإشارة: 📉 *PUT*\n"
        f"الثقة: 65%\n"
        f"الدخول: `24,200 – 24,500`\n"
        f"SL: `24,700`\n"
        f"TP1: `23,779` \\(RR 1:2.1\\)\n"
        f"TP2: `23,410` \\(RR 1:3.9\\)\n\n"
        f"🌙 *الفواصل الفلكية:* فاصل انتقالي D1/H4 — يدعم PUT\n"
        f"⏰ *الجلسة:* {get_session()}\n\n"
        f"⚠️ للأغراض التعليمية فقط — ليس توصية استثمارية"
    )
    await msg.reply_text(text, parse_mode="MarkdownV2")

async def cmd_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    d = PRICES["spx"]
    nd = PRICES["ndx"]
    day = ksa_now().day
    evs = ASTRO_APRIL.get(day, []) if ksa_now().month == 4 else []
    evs_txt = "\n".join([f"• {e[0]}" for e in evs]) if evs else "لا توجد فواصل خاصة"
    identity = "🔥 نارية — تذبذب عالٍ" if day < 20 else "🌿 ترابية — تذبذب بطيء"
    trend = "📈 صاعد (2/4–17/4)" if day < 17 else "📉 هابط (17/4–1/5)"

    text = (
        f"📋 *التقرير اليومي — {ksa_now().strftime('%d/%m/%Y')}*\n"
        f"{'─'*30}\n\n"
        f"📊 *SPX:* `{d['price']:,.0f}` | VIX: `{d['vix']}`\n"
        f"📊 *NDX:* `{nd['price']:,.0f}`\n\n"
        f"🎯 *الإشارة:* 📉 PUT على كلا المؤشرين\n\n"
        f"🌙 *فلكي اليوم:*\n{evs_txt}\n\n"
        f"🌟 هوية: {identity}\n"
        f"📈 اتجاه: {trend}\n\n"
        f"⏰ الجلسة: {get_session()}\n"
        f"🔄 آخر تحديث: {PRICES['updated']}\n\n"
        f"⚠️ للأغراض التعليمية فقط"
    )
    await msg.reply_text(text, parse_mode="Markdown")

async def cmd_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    PENDING_UPDATE[msg.chat_id] = "spx_price"
    await msg.reply_text(
        "✏️ *تحديث الأسعار*\n\n"
        "أرسل سعر SPX الحالي\n"
        "مثال: `6820`",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()

    if chat_id not in PENDING_UPDATE:
        return

    step = PENDING_UPDATE[chat_id]

    try:
        val = float(text.replace(",", ""))
    except:
        await update.message.reply_text("❌ أرسل رقماً صحيحاً")
        return

    if step == "spx_price":
        PRICES["spx"]["price"] = val
        PENDING_UPDATE[chat_id] = "spx_prev"
        await update.message.reply_text(f"✅ SPX: `{val:,.0f}`\n\nأرسل إغلاق الأمس PDC:", parse_mode="Markdown")

    elif step == "spx_prev":
        PRICES["spx"]["prev"] = val
        PENDING_UPDATE[chat_id] = "spx_high"
        await update.message.reply_text(f"✅ PDC: `{val:,.0f}`\n\nأرسل High اليوم:", parse_mode="Markdown")

    elif step == "spx_high":
        PRICES["spx"]["high"] = val
        PENDING_UPDATE[chat_id] = "spx_low"
        await update.message.reply_text(f"✅ High: `{val:,.0f}`\n\nأرسل Low اليوم:", parse_mode="Markdown")

    elif step == "spx_low":
        PRICES["spx"]["low"] = val
        PENDING_UPDATE[chat_id] = "vix"
        await update.message.reply_text(f"✅ Low: `{val:,.0f}`\n\nأرسل VIX:", parse_mode="Markdown")

    elif step == "vix":
        PRICES["spx"]["vix"] = val
        PENDING_UPDATE[chat_id] = "ndx_price"
        await update.message.reply_text(f"✅ VIX: `{val}`\n\nأرسل سعر NDX:", parse_mode="Markdown")

    elif step == "ndx_price":
        PRICES["ndx"]["price"] = val
        PENDING_UPDATE[chat_id] = "ndx_high"
        await update.message.reply_text(f"✅ NDX: `{val:,.0f}`\n\nأرسل High NDX:", parse_mode="Markdown")

    elif step == "ndx_high":
        PRICES["ndx"]["high"] = val
        PENDING_UPDATE[chat_id] = "ndx_low"
        await update.message.reply_text(f"✅ High NDX: `{val:,.0f}`\n\nأرسل Low NDX:", parse_mode="Markdown")

    elif step == "ndx_low":
        PRICES["ndx"]["low"] = val
        PRICES["ndx"]["prev"] = PRICES["ndx"].get("prev", val)
        now_str = ksa_now().strftime("%H:%M KSA")
        PRICES["updated"] = now_str
        del PENDING_UPDATE[chat_id]
        await update.message.reply_text(
            f"✅ *تم تحديث جميع الأسعار!*\n\n"
            f"SPX: `{PRICES['spx']['price']:,.0f}` | VIX: `{PRICES['spx']['vix']}`\n"
            f"NDX: `{PRICES['ndx']['price']:,.0f}`\n"
            f"🕐 {now_str}\n\n"
            f"استخدم /spx أو /ndx للتحليل الكامل",
            parse_mode="Markdown"
        )

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "spx":   await cmd_spx(update, ctx)
    elif data == "ndx": await cmd_ndx(update, ctx)
    elif data == "astro": await cmd_astro(update, ctx)
    elif data == "signal": await cmd_signal(update, ctx)
    elif data == "update": await cmd_update(update, ctx)

async def daily_report(ctx: ContextTypes.DEFAULT_TYPE):
    """يُرسَل تلقائياً عند NY Open (4:30pm KSA = 1:30 UTC)"""
    # يحتاج chat_id محفوظ — يُضاف لاحقاً
    pass

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("spx", cmd_spx))
    app.add_handler(CommandHandler("ndx", cmd_ndx))
    app.add_handler(CommandHandler("astro", cmd_astro))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 ICT Bot شغّال!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
