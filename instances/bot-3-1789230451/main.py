import asyncio, logging, secrets, string, os, shutil, tempfile, sqlite3
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from config import BOT_TOKEN, OWNER_ID, APP_NAME
from database.core import init_database, get_connection
from database.admins import add_admin, is_admin, list_admin_ids
from database.users import upsert_user, get_user, get_user_by_tid, set_balance, list_users, is_blocked, set_blocked, approve_topup, reject_topup
from database.panels import add_panel, get_panels, get_panel, update_panel, delete_panel
from database.products import create_product, list_products, get_product, toggle_product, reserve_product, release_product, get_custom, save_custom, custom_price
from database.finance import add_method, get_method, list_methods, create_coupon, list_coupons, get_coupon, coupon_usage_count, user_coupon_usage, redeem_coupon, coupon_available, reserve_coupon, finalize_coupon
from database.orders import create_order, get_order, set_order, list_pending, claim_for_processing
from database.reports import save as save_reports, get_config as get_reports_config, topics as report_topics
from pasarguard import PasarGuardAPI

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log=logging.getLogger(__name__)
init_database(); add_admin(OWNER_ID,'owner')

def admin(uid): return uid==OWNER_ID or is_admin(uid)
def B(text,data,style='primary'):
    kw={'text':text,'callback_data':data,'style':style}
    return InlineKeyboardButton(**kw)
def U(text,url):
    return InlineKeyboardButton(text=text,url=url)
def KB(rows): return InlineKeyboardMarkup(rows)
def now(): return datetime.now(timezone.utc)
def money(n): return f'{int(n):,} تومان'
def vol(gb): return 'نامحدود' if not gb else f'{gb} گیگ'
def duration(days): return 'نامحدود' if not days else f'{days} روز'
def customer_url(base):
    base=base.rstrip('/')
    return base[:-len('/dashboard')] + '/dashboard' if base.lower().endswith('/dashboard') else base + '/dashboard'
def api_base_url(base):
    base=base.rstrip('/')
    return base[:-len('/dashboard')] if base.lower().endswith('/dashboard') else base

def get_setting(key, default=''):
    db=get_connection(); r=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); db.close(); return r[0] if r else default
def save_setting(key,value):
    db=get_connection(); db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value))); db.commit(); db.close()
def setting_bool(key,default=False):
    return get_setting(key,'1' if default else '0') in ('1','true','True','on','yes')
def setting_text(key,default):
    value=get_setting(key,'')
    return value if value else default
def audit(action,admin_id=0,details=''):
    try:
        db=get_connection(); db.execute('INSERT INTO admin_logs(admin_id,action,details) VALUES(?,?,?)',(admin_id,action,details)); db.commit(); db.close()
    except Exception: log.exception('audit log failed')

async def send_database_backup(bot,chat_id):
    src=__import__('database.core',fromlist=['DB_PATH']).DB_PATH
    fd,path=tempfile.mkstemp(prefix='pasarguard-backup-',suffix='.db'); os.close(fd)
    try:
        srcdb=sqlite3.connect(src); dst=sqlite3.connect(path); srcdb.backup(dst); dst.close(); srcdb.close()
        with open(path,'rb') as f: await bot.send_document(chat_id,f,filename=os.path.basename(path),caption='💾 بکاپ سالم و کامل دیتابیس ربات')
    finally:
        try: os.remove(path)
        except OSError: pass

async def restore_database_from_telegram(u,c):
    if not admin(u.effective_user.id): return
    doc=u.message.document
    if not doc or not doc.file_name.lower().endswith('.db'):
        await u.message.reply_text('❌ فقط فایل دیتابیس با پسوند .db قابل بازیابی است.'); return
    tmp=tempfile.mktemp(prefix='pasarguard-restore-',suffix='.db'); f=await doc.get_file(); await f.download_to_drive(tmp)
    try:
        test=sqlite3.connect(tmp); ok=test.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; tables={r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type='table'")}; test.close()
        required={'users','panels','products','orders','services','transactions','settings'}
        if not ok or not required.issubset(tables): raise ValueError('فایل دیتابیس معتبر یا متعلق به این ربات نیست.')
        c.user_data['pending_restore_path']=tmp
        await u.message.reply_text('⚠️ بازیابی دیتابیس\n\nاین عملیات دیتابیس فعلی را با فایل ارسالی جایگزین می‌کند.\n💾 قبل از جایگزینی، نسخه فعلی با نام before-restore نگه داشته می‌شود.\n\nاگر مطمئن هستید ادامه دهید:',reply_markup=KB([[B('🔴 تأیید بازیابی','confirm_restore','danger')],[B('↩️ لغو','cancel_restore')]]))
    except Exception as e:
        try: os.remove(tmp)
        except OSError: pass
        await u.message.reply_text('❌ فایل قابل بازیابی نیست.\n'+str(e)[:500])

def home(uid):
    if is_blocked((get_user_by_tid(uid) or {}).get('id',-1)):
        return KB([[B('🚫 حساب مسدود','noop','danger')]])
    rows=[[B('📦 تهیه پنل','buy_panel','primary')],[B('🖥️ پنل‌های من','my_panels','primary'),B('💰 کیف پول','wallet')],[B('👤 حساب من','account'),B('💬 پشتیبانی','support')]]
    if admin(uid): rows.append([B('⚙️ پنل مدیریت','admin','primary')])
    return KB(rows)

async def start(u,c):
    x=u.effective_user; upsert_user(x.id,x.username,x.first_name); c.user_data.clear()
    await u.message.reply_text(setting_text('welcome_text',f'👋 سلام!\n\nبه {setting_text("bot_name",APP_NAME)} خوش اومدی.'),reply_markup=home(x.id))

async def admin_panel(q):
    await q.edit_message_text('⚙️ پنل مدیریت',reply_markup=KB([
        [B('👥 کاربران','admin_users','primary'),B('🖥️ پنل‌ها','admin_panels','primary')],
        [B('📦 پلن‌ها','admin_products','primary')],[B('💰 مرکز مالی','admin_finance','primary')],
        [B('📜 لاگ عملیات','admin_logs')],
        [B('📊 گزارش‌ها','admin_reports','primary'),B('⚙️ تنظیمات','admin_settings')],[B('💾 بکاپ دیتابیس','db_backup','primary')],[B('↩️ بازگشت','home')]
    ]))

async def users_menu(q):
    await q.edit_message_text('👥 کاربران\n\nیک دسته را انتخاب کن:',reply_markup=KB([
        [B('👤 همه','users:all'),B('🛒 خریداران','users:buyers')],
        [B('🚫 بدون خرید','users:nonbuyers'),B('💰 دارای موجودی','users:balance')],
        [B('🔎 جستجو','users:search','primary')],[B('↩️ بازگشت','admin')]]))

def user_details_text(uid):
    usr=get_user(uid)
    if not usr: return None,None
    db=get_connection()
    orders=db.execute('SELECT COUNT(*) c, COALESCE(SUM(CASE WHEN status="completed" THEN 1 ELSE 0 END),0) completed, COALESCE(SUM(total_amount),0) spent FROM orders WHERE user_id=?',(uid,)).fetchone()
    services=db.execute('SELECT COUNT(*) c FROM services WHERE user_id=?',(uid,)).fetchone()
    last=db.execute('SELECT created_at,status,total_amount FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
    db.close()
    uname='@'+usr['username'] if usr.get('username') else '-'
    text=(f'👤 اطلاعات کامل کاربر\n\n🆔 Telegram ID: <code>{usr["telegram_id"]}</code>\n'
          f'👤 Username تلگرام: {uname}\n📝 نام: {usr.get("first_name") or "-"}\n'
          f'💰 موجودی کیف پول: <b>{money(usr.get("balance",0))}</b>\n'
          f'📦 سرویس‌های فعال/ثبت‌شده: {services[0]}\n'
          f'🛒 تعداد سفارش‌ها: {orders[0]}\n🟢 سفارش‌های تکمیل‌شده: {orders[1]}\n'
          f'💳 مجموع مبلغ سفارش‌ها: {money(orders[2])}\n📅 تاریخ عضویت: {usr.get("created_at") or "-"}\n'
          f'🧾 آخرین سفارش: {last[1] if last else "-"} / {money(last[2]) if last else "-"}')
    return usr,text

async def users_list(q,mode):
    rows=[]
    for x in list_users(mode): rows.append([B(f"👤 {x['username'] or x['first_name'] or x['telegram_id']} | {x.get('balance',0):,}",f'user:{x["id"]}')])
    rows.append([B('↩️ کاربران','admin_users')]); await q.edit_message_text('👥 نتیجه کاربران',reply_markup=KB(rows or [[B('📭 موردی نیست','noop')]]))

async def user_details(q,uid):
    usr,text=user_details_text(uid)
    if not usr: await q.edit_message_text('❌ کاربر پیدا نشد.',reply_markup=KB([[B('↩️ کاربران','admin_users')]])); return
    blocked=is_blocked(uid); block_btn=B('🟢 رفع مسدودی','user_unblock:'+str(uid),'success') if blocked else B('🔴 مسدود کردن','user_block:'+str(uid),'danger')
    rows=[[B('💰 مدیریت کیف پول','user_wallet:'+str(uid),'primary')],[block_btn],[B('📦 سرویس‌ها','user_services:'+str(uid),'primary')],[B('🧾 سفارش‌ها','user_orders:'+str(uid),'primary')],[B('↩️ کاربران','admin_users')]]
    await q.edit_message_text(text,parse_mode='HTML',reply_markup=KB(rows))

async def user_services(q,uid):
    usr=get_user(uid)
    if not usr: return
    db=get_connection(); rows=db.execute('SELECT s.*,p.name panel_name,p.url FROM services s JOIN panels p ON p.id=s.panel_id WHERE s.user_id=? ORDER BY s.id DESC',(uid,)).fetchall(); db.close()
    text='📦 سرویس‌های کاربر\n\n'
    if not rows: text+='📭 سرویس فعالی/ثبت‌شده‌ای ندارد.'
    for r in rows:
        text += (f'🆔 سرویس #{r["id"]}\n🖥️ پنل: {r["panel_name"]}\n👤 Username: <code>{r["username"]}</code>\n'
                 f'🔑 Password: <code>{r["password"]}</code>\n🟢 وضعیت: {r["status"]}\n'
                 f'🔗 {customer_url(r["url"])}\n\n')
    await q.edit_message_text(text,parse_mode='HTML',reply_markup=KB([[B('↩️ کاربر','user:'+str(uid))]]))

async def user_orders(q,uid):
    db=get_connection(); rows=db.execute('SELECT id,status,total_amount,created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 30',(uid,)).fetchall(); db.close()
    text='🧾 سفارش‌های کاربر\n\n' + ('\n'.join(f'#{r["id"]} | {r["status"]} | {money(r["total_amount"])} | {r["created_at"]}' for r in rows) if rows else '📭 سفارشی ندارد.')
    await q.edit_message_text(text,reply_markup=KB([[B('↩️ کاربر','user:'+str(uid))]]))

async def user_wallet(q,uid):
    usr=get_user(uid)
    if not usr: return
    await q.edit_message_text(f'💰 کیف پول کاربر\n\nموجودی فعلی: {money(usr.get("balance",0))}',reply_markup=KB([[B('➕ افزایش موجودی','wallet_add:'+str(uid),'success'),B('➖ کاهش موجودی','wallet_sub:'+str(uid),'danger')],[B('↩️ کاربر','user:'+str(uid))]]))

async def pending_orders(q):
    db=get_connection(); rows=db.execute('SELECT o.*,u.username AS telegram_username,p.name panel_name FROM orders o JOIN users u ON u.id=o.user_id JOIN panels p ON p.id=o.panel_id WHERE o.status IN ("awaiting_receipt","pending_review","provisioning") ORDER BY o.id ASC LIMIT 50').fetchall(); db.close()
    if not rows:
        await q.edit_message_text('⏳ سفارش در انتظاری وجود ندارد.',reply_markup=KB([[B('↩️ مدیریت','admin')]])); return
    text='⏳ سفارش‌های در انتظار\n\n'+'\n'.join(f'#{r["id"]} | @{r["telegram_username"] or "-"} | {r["panel_name"]} | {r["status"]} | {money(r["total_amount"])}' for r in rows)
    await q.edit_message_text(text,reply_markup=KB([[B('🔄 تازه‌سازی','admin_pending','primary')],[B('↩️ مدیریت','admin')]]))

async def admin_logs(q):
    db=get_connection(); rows=db.execute('SELECT * FROM admin_logs ORDER BY id DESC LIMIT 30').fetchall(); db.close()
    text='📜 لاگ عملیات ادمین\n\n' + ('\n'.join(f'#{r["id"]} | {r["action"]} | admin={r["admin_id"]} | {r["details"]} | {r["created_at"]}' for r in rows) if rows else '📭 لاگی ثبت نشده.')
    await q.edit_message_text(text,reply_markup=KB([[B('↩️ مدیریت','admin')]]))

async def panels_menu(q):
    rows=[[B('➕ افزودن پنل','panel_add','success')]]
    for p in get_panels(): rows.append([B(('🟢 ' if p['status']=='online' else '🔴 ')+p['name'],f'panel:{p["id"]}')])
    rows.append([B('↩️ بازگشت','admin')]); await q.edit_message_text('🖥️ پنل‌های PasarGuard',reply_markup=KB(rows))

async def products_menu(q):
    rows=[[B('➕ پلن پیشنهادی','prod_add','success')],[B('⚙️ تنظیم پلن دلخواه','custom_settings','primary')]]
    for p in list_products(): rows.append([B(f"{'🟢' if p['enabled'] else '🔴'} {p['name']} | {p['price']:,}",f'prod:{p["id"]}')])
    rows.append([B('↩️ بازگشت','admin')]); await q.edit_message_text('📦 پلن‌ها',reply_markup=KB(rows))

def volume_options(s):
    lo=max(1,int(s.get('min_gb',1) or 1)); hi=int(s.get('max_gb',0) or 0)
    # Fixed, useful presets. Prices are calculated dynamically from the admin's
    # current price_per_gb; never turn a huge max_gb (e.g. 100000) into a button.
    # User-facing presets: 100GB increments only; never create huge accidental buttons.
    presets=tuple(range(100, 1001, 100))
    vals=[v for v in presets if v>=lo and (not hi or v<=hi)]
    return vals[:10]

def duration_options(s):
    lo=max(1,int(s.get('min_days',1) or 1)); hi=int(s.get('max_days',0) or 0)
    if not hi: return []
    presets=[30,60,90,120,180,365]
    vals=[x for x in presets if lo<=x<=hi]
    if lo not in vals: vals.insert(0,lo)
    if hi not in vals: vals.append(hi)
    return sorted(set(vals))[:8]

async def custom_settings(q,c):
    s=get_custom(); state='روشن' if s['enabled'] else 'خاموش'; ask='بله' if s.get('ask_duration',1) else 'خیر'
    default='نامحدود' if not s.get('default_days') else f'{s["default_days"]} روز'
    txt=(f'⚙️ تنظیم پلن دلخواه\n\n🟢 وضعیت: {state}\n'
         f'📊 حداقل حجم: {s["min_gb"]} گیگ\n📊 حداکثر حجم: {s["max_gb"] or "نامحدود"}\n'
         f'💰 قیمت هر گیگ: {s["price_per_gb"]:,} تومان\n'
         f'📅 حداقل روز: {s["min_days"]}\n📅 حداکثر روز: {s["max_days"] or "نامحدود"}\n'
         f'💰 قیمت هر روز: {s.get("price_per_day",0):,} تومان\n'
         f'💰 قیمت ماهانه برای حجم+مدت نامحدود: {s.get("price_per_month",0):,} تومان\n'
         f'💰 قیمت حجم محدود + مدت نامحدود: {s.get("price_limited_unlimited",0):,} تومان\n'
         f'⏱ پرسیدن مدت از کاربر: {ask}\n📌 مدت پیش‌فرض وقتی پرسیده نمی‌شود: {default}')
    rows=[[B('🟢 فعال','custom_toggle:1','success'),B('🔴 غیرفعال','custom_toggle:0','danger')],
          [B('✏️ حداقل گیگ','custom_field:min_gb'),B('✏️ حداکثر گیگ','custom_field:max_gb')],
          [B('✏️ قیمت هر گیگ','custom_field:price_per_gb')],
          [B('✏️ حداقل روز','custom_field:min_days'),B('✏️ حداکثر روز','custom_field:max_days')],
          [B('✏️ قیمت هر روز','custom_field:price_per_day')],
          [B('✏️ قیمت ماهانه','custom_field:price_per_month')],[B('✏️ قیمت حجم محدود + مدت نامحدود','custom_field:price_limited_unlimited')],
          [B('⏱ پرسیدن مدت: '+ask,'custom_ask_duration','primary')],
          [B('📌 مدت پیش‌فرض','custom_field:default_days')],
          [B('↩️ پلن‌ها','admin_products')]]
    await q.edit_message_text(txt,reply_markup=KB(rows))

async def finance(q):
    m=get_method(); txt='💰 مرکز مالی\n\n'
    if m:
        txt += f"💳 کارت به کارت: 🟢 فعال\n💳 شماره کارت: {m.get('card_number') or '-'}\n👤 صاحب کارت: {m.get('card_holder') or '-'}\n"
        txt += f"🤖 تأیید خودکار: {'🟢 روشن' if m.get('auto_approve') else '⚪ خاموش'}"
        if m.get('auto_approve'): txt += f"\n⏱ زمان تأیید خودکار: {m.get('auto_approve_minutes',5)} دقیقه"
    else: txt+='📭 هنوز روش پرداختی ثبت نشده.\n'
    txt+=f'\n\n🎟 کدهای تخفیف: {len(list_coupons())}'
    await q.edit_message_text(txt,reply_markup=KB([[B('💳 کارت به کارت','card_setup','primary')],[B('🤖 تنظیم تأیید خودکار','auto_settings','primary')],[B('🎟 کد تخفیف','coupon_setup','primary')],[B('↩️ بازگشت','admin')]]))

async def auto_settings(q,c):
    m=get_method()
    if not m:
        await q.edit_message_text('📭 ابتدا روش کارت‌به‌کارت را تنظیم کن.',reply_markup=KB([[B('💳 کارت به کارت','card_setup','primary')],[B('↩️ مالی','admin_finance')]])); return
    state='🟢 روشن' if m.get('auto_approve') else '⚪ خاموش'
    delay=int(m.get('auto_approve_minutes') or 5)
    text=f'🤖 تنظیم تأیید خودکار\n\nوضعیت: {state}\n⏱ تأخیر: {delay} دقیقه\n\nبا روشن بودن این گزینه، پس از ارسال رسید، سفارش بعد از این مدت خودکار برای ساخت سرویس تأیید می‌شود.'
    await q.edit_message_text(text,reply_markup=KB([[B('🟢 روشن','auto_toggle:1','success'),B('⚪ خاموش','auto_toggle:0')],[B('⏱ تغییر زمان','auto_delay','primary')],[B('↩️ مالی','admin_finance')]]))

async def coupon_kind(q,c):
    c.user_data.clear(); c.user_data.update({'state':'coupon_value','coupon_kind':'percent' if q.data.endswith('percent') else 'fixed'})
    await q.edit_message_text('💰 مقدار تخفیف را وارد کن:')

async def general_settings(q,c):
    text='⚙️ تنظیمات عمومی\n\nیک بخش را انتخاب کن:'
    await q.edit_message_text(text,reply_markup=KB([[B('🎨 متن و ظاهر','settings_text','primary')],[B('💳 پرداخت','settings_payment','primary')],[B('🛒 خرید','settings_purchase','primary')],[B('🔔 اعلان‌ها','settings_notify','primary')],[B('💬 پشتیبانی','settings_support','primary')],[B('🛡️ امنیت','settings_security','primary')],[B('↩️ مدیریت','admin')]]))

async def settings_text(q,c):
    await q.edit_message_text(f'🎨 متن و ظاهر\n\nنام فعلی ربات: {get_setting("bot_name",APP_NAME)}\n\nبرای تغییر نام دکمه زیر را بزن.',reply_markup=KB([[B('✏️ تغییر نام ربات','set:bot_name','primary')],[B('✏️ متن خوش‌آمدگویی','set:welcome_text','primary')],[B('✏️ متن پشتیبانی','set:support_text','primary')],[B('↩️ تنظیمات','admin_settings')]]))
async def settings_payment(q,c):
    m=get_method(); await q.edit_message_text(f'💳 پرداخت\n\nروش فعال: {"کارت‌به‌کارت" if m else "هیچ‌کدام"}\nتأیید خودکار: {"روشن" if m and m.get("auto_approve") else "خاموش"}\nتأخیر: {int(m.get("auto_approve_minutes",5)) if m else "-"} دقیقه',reply_markup=KB([[B('💳 مدیریت کارت','card_setup','primary')],[B('🤖 تنظیم تأیید خودکار','auto_settings','primary')],[B('↩️ تنظیمات','admin_settings')]]))
async def settings_purchase(q,c):
    await q.edit_message_text(f'🛒 خرید\n\nخلاصه سفارش: {"🟢 فعال" if setting_bool("order_summary",True) else "⚪ خاموش"}\nتمدید سرویس: {"🟢 فعال" if setting_bool("service_renewal_enabled",True) else "⚪ خاموش"}\nافزایش حجم: {"🟢 فعال" if setting_bool("service_volume_add_enabled",True) else "⚪ خاموش"}\nلغو سرویس: {"🟢 فعال" if setting_bool("service_revoke_enabled",True) else "⚪ خاموش"}\nجلوگیری از تأیید تکراری: 🟢 فعال\nساخت سرویس فقط بعد از تأیید پرداخت: 🟢 فعال',reply_markup=KB([[B('🔄 خلاصه سفارش','toggle:order_summary','primary')],[B('🔄 تمدید سرویس','toggle:service_renewal_enabled','primary')],[B('🔄 افزایش حجم','toggle:service_volume_add_enabled','primary')],[B('🔄 لغو سرویس','toggle:service_revoke_enabled','primary')],[B('↩️ تنظیمات','admin_settings')]]))
async def settings_notify(q,c):
    await q.edit_message_text(f'🔔 اعلان‌ها\n\nارسال رسید برای ادمین‌ها: {"🟢 فعال" if setting_bool("notify_admin_receipt",True) else "⚪ خاموش"}\nگزارش رسید در Topic پرداخت: {"🟢 فعال" if setting_bool("notify_report_receipt",True) else "⚪ خاموش"}',reply_markup=KB([[B('🔄 رسید → ادمین','toggle:notify_admin_receipt','primary')],[B('🔄 رسید → گزارش‌ها','toggle:notify_report_receipt','primary')],[B('↩️ تنظیمات','admin_settings')]]))
async def settings_support(q,c):
    text=setting_text('support_text','💬 برای پشتیبانی با ادمین در ارتباط باشید.')
    username=get_setting('support_username','').strip()
    link=get_setting('support_link','').strip()
    await q.edit_message_text(
        '💬 تنظیمات پشتیبانی\n\n'
        f'📝 متن: {text}\n'
        f'👤 Username: {username or "تنظیم نشده"}\n'
        f'🔗 لینک: {link or "تنظیم نشده"}\n\n'
        'این اطلاعات در بخش «💬 پشتیبانی» برای کاربران نمایش داده می‌شود.\n'
        'پیشنهاد می‌شود متن راهنما و حداقل یکی از Username یا لینک تماس را تنظیم کنید.',
        reply_markup=KB([
            [B('📝 متن پشتیبانی','set:support_text','primary')],
            [B('👤 Username پشتیبانی','set:support_username','primary')],
            [B('🔗 لینک پشتیبانی','set:support_link','primary')],
            [B('↩️ تنظیمات عمومی','admin_settings')]
        ])
    )

async def settings_security(q,c):
    await q.edit_message_text('🛡️ امنیت\n\n🔐 رمز پنل: حداقل 12 کاراکتر + 2 حرف بزرگ + 2 حرف کوچک + 2 عدد + 1 نماد\n🧱 جلوگیری از تأیید دوباره سفارش: فعال\n🔒 ساخت PasarGuard قبل از تأیید پرداخت: ممنوع',reply_markup=KB([[B('↩️ تنظیمات','admin_settings')]]))

async def buy_start(q,c):
    ps=get_panels()
    if not ps: await q.edit_message_text('❌ فعلاً هیچ پنلی برای فروش ثبت نشده.',reply_markup=home(q.from_user.id)); return
    c.user_data.clear(); c.user_data['state']='choose_panel'; await q.edit_message_text('🖥️ کدام پنل را برای خرید انتخاب می‌کنید؟',reply_markup=KB([[B(p['name'],f'buy_panel:{p["id"]}','primary')] for p in ps]+[[B('↩️ بازگشت','home')]]))
async def choose_panel(q,c,pid):
    if not get_panel(pid): return
    c.user_data.update({'panel_id':pid,'selected_panel_id':pid,'state':'choose_kind'}); await q.edit_message_text('نوع پلن را انتخاب کنید:',reply_markup=KB([[B('⭐ پلن پیشنهادی','buy_suggest','primary')],[B('⚙️ پلن دلخواه','buy_custom','primary')],[B('↩️ بازگشت','buy_panel')]]))
async def suggested(q,c):
    ps=list_products(True)
    if not ps: await q.edit_message_text('📭 پلن فعالی موجود نیست.',reply_markup=KB([[B('↩️ بازگشت','buy_panel')]])); return
    c.user_data['state']='choose_product'; await q.edit_message_text('⭐ پلن پیشنهادی را انتخاب کنید:',reply_markup=KB([[B(f"{p['name']} | {p['price']:,} تومان",f'buy_prod:{p["id"]}','primary')] for p in ps]+[[B('↩️ بازگشت','buy_panel')]]))

def randpass():
    # Generate a password that ALWAYS satisfies PasarGuard's password policy.
    upper = ''.join(secrets.choice(string.ascii_uppercase) for _ in range(2))
    lower = ''.join(secrets.choice(string.ascii_lowercase) for _ in range(2))
    digits = ''.join(secrets.choice(string.digits) for _ in range(2))
    special = secrets.choice('!@#$%^&*')
    rest = ''.join(secrets.choice(string.ascii_letters + string.digits + '!@#$%^&*') for _ in range(6))
    chars = list(upper + lower + digits + special + rest)
    secrets.SystemRandom().shuffle(chars)
    password = ''.join(chars)
    # Defensive check: never return a password that fails our validator.
    if not validpass(password):
        return randpass()
    return password
def valid_username(x): return bool(x) and len(x)<=32 and all(ch in string.ascii_letters+string.digits for ch in x)
def validpass(x): return len(x)>=12 and sum(a.isupper() for a in x)>=2 and sum(a.islower() for a in x)>=2 and sum(a.isdigit() for a in x)>=2 and sum(a in '!@#$%^&*' for a in x)>=1
def randuser(): return 'Arman'+''.join(secrets.choice(string.digits) for _ in range(6))
async def after_plan(q,c,total,kind,product=None,gb=0,days=0,users=0):
    if c.user_data.get('panel_id') is None and c.user_data.get('selected_panel_id') is not None:
        c.user_data['panel_id'] = c.user_data['selected_panel_id']
    c.user_data.update({'state':'username','kind':kind,'total':total,'base_total':total,'discount_amount':0,'product_id':product['id'] if product else None,'gb':gb,'days':days,'users':users})
    await q.edit_message_text('👤 Username پنل را وارد کنید.\n\nفقط حروف انگلیسی (A-Z / a-z) و عدد مجاز است؛ فاصله، حروف فارسی و نمادهای خاص استفاده نکنید.\nمثال: Arman7429\n\nاگر دوست دارید ربات خودش بسازد، دکمه زیر را بزنید.',reply_markup=KB([[B('🎲 ساخت نام کاربری تصادفی','random_username','primary')]]))
async def custom_start(q,c):
    s=get_custom()
    if not s['enabled']:
        await q.edit_message_text('🔴 پلن دلخواه فعلاً غیرفعال است.',reply_markup=KB([[B('↩️ بازگشت','buy_panel')]])); return
    # Keep the selected panel; custom_start must not wipe it from user_data.
    panel_id = c.user_data.get('panel_id') or c.user_data.get('selected_panel_id')
    c.user_data.clear()
    if panel_id is not None:
        c.user_data['panel_id'] = panel_id
        c.user_data['selected_panel_id'] = panel_id
    c.user_data['state']='custom_gb'
    rows=[]; row=[]
    for v in volume_options(s):
        price=v*int(s.get('price_per_gb',0) or 0); label='1 ترا' if v==1000 else f'{v} گیگ'
        row.append(B(f'{label} — {money(price)}',f'custom_gb:{v}','primary'))
        if len(row)==2: rows.append(row); row=[]
    if row: rows.append(row)
    rows.append([B('♾️ حجم نامحدود','custom_gb:0','success')])
    rows.append([B('✏️ حجم دلخواه','custom_gb_custom','primary')])
    await q.edit_message_text(
        f'📊 حجم سرویس را انتخاب کنید\n\nبرای راحتی شما چند حجم پیشنهادی قرار داده‌ایم.\n💰 قیمت هر گیگ: {s["price_per_gb"]:,} تومان\n\nبرای حجم دلخواه می‌توانید مقدار را دستی وارد کنید.',
        reply_markup=KB(rows))

async def show_custom_days(q,c):
    s=get_custom(); gb=int(c.user_data.get('gb',0) or 0); rows=[]
    if gb==0:
        monthly=int(s.get('price_per_month',0) or 0)
        for months in (1,3,6,12):
            price=months*monthly
            rows.append([B(f'{months} ماه — {money(price)}',f'custom_months:{months}','primary')])
        rows.append([B('✏️ تعداد ماه دلخواه','custom_months_custom','primary')])
        info=f'♾️ حجم نامحدود\n💰 قیمت هر ماه: {monthly:,} تومان'
        text=f'📅 مدت سرویس را به صورت ماهانه انتخاب کنید\n\n{info}\n\n⚠️ چون حجم نامحدود انتخاب شده، هزینه بر اساس روز محاسبه نمی‌شود و هر ماه با قیمت ماهانه ادمین محاسبه خواهد شد.'
        await q.edit_message_text(text,reply_markup=KB(rows)); return
    for d in duration_options(s):
        price=gb*int(s.get('price_per_gb',0) or 0)+d*int(s.get('price_per_day',0) or 0)
        rows.append([B(f'{d} روز — {money(price)}',f'custom_days:{d}','primary')])
    unlimited_price=int(s.get('price_limited_unlimited',0) or 0) or gb*int(s.get('price_per_gb',0) or 0)
    unlimited_label='♾️ مدت نامحدود' if gb==0 else f'♾️ مدت نامحدود — {money(unlimited_price)}'
    rows.append([B(unlimited_label,'custom_days:0','success')])
    rows.append([B('✏️ مدت دلخواه','custom_days_custom','primary')])
    info=f'📊 حجم: {gb} گیگ\n💰 قیمت هر گیگ: {s["price_per_gb"]:,} تومان\n💰 قیمت هر روز: {s["price_per_day"]:,} تومان'
    await q.edit_message_text(f'📅 مدت سرویس را انتخاب کنید\n\n{info}\n\nقیمت هر گزینه شامل هزینه حجم و مدت است.',reply_markup=KB(rows))

async def checkout(u,c):
    chat_id=u.effective_user.id; d=c.user_data
    required=('total','panel_id','kind','username','password')
    if any(k not in d for k in required):
        await c.bot.send_message(chat_id=chat_id,text='❌ اطلاعات سفارش ناقص شده است. لطفاً خرید را از ابتدا شروع کنید.',reply_markup=home(chat_id)); d.clear(); return
    uid=get_user_by_tid(chat_id)
    if not uid: d.clear(); await c.bot.send_message(chat_id=chat_id,text='❌ حساب کاربری پیدا نشد.',reply_markup=home(chat_id)); return
    base_total=int(d.get('base_total',d['total'])); discount=int(d.get('discount_amount',0) or 0); total=max(0,base_total-discount); d['total']=total
    # Validate service operations immediately before payment.
    if d.get('kind') in ('renewal','volume_add'):
        db=get_connection(); sr=db.execute('SELECT * FROM services WHERE id=? AND user_id=?',(int(d.get('target_service_id',0)),uid['id'])).fetchone(); db.close()
        if not sr or sr['status']=='revoked':
            d.clear(); await c.bot.send_message(chat_id=chat_id,text='❌ سرویس موردنظر دیگر قابل استفاده نیست.',reply_markup=home(chat_id)); return
    # Reserve the coupon only when the order is actually created.
    wallet=max(0,int(uid.get('balance',0))); w=min(wallet,total); card=total-w
    if w: set_balance(uid['id'],-w,'order_hold','رزرو برای سفارش')
    try:
        o=create_order(user_id=uid['id'],panel_id=d['panel_id'],product_id=d.get('product_id'),kind=d['kind'],total_amount=total,wallet_amount=w,card_amount=card,username=d['username'],password=d['password'],custom_gb=d.get('gb',0),custom_days=d.get('days',0),custom_users=d.get('users',0),target_service_id=d.get('target_service_id'),coupon_code=d.get('coupon_code'),discount_amount=discount,status='paid' if not card else 'awaiting_receipt')
        if d.get('coupon_code'): reserve_coupon(d['coupon_code'],uid['id'],o['id'])
    except Exception as e:
        if 'o' in locals(): set_order(o['id'],status='rejected',rejected_at=now().isoformat(),error=str(e)[:500])
        if w: set_balance(uid['id'],w,'refund','بازگشت رزرو به علت خطای ثبت سفارش',o['id'] if 'o' in locals() else None)
        raise
    if card:
        m=get_method()
        if not m:
            if w: set_balance(uid['id'],w,'refund','روش پرداخت موجود نیست',o['id'])
            if d.get('coupon_code'): finalize_coupon(o['id'],False)
            set_order(o['id'],status='rejected',rejected_at=now().isoformat(),error='no payment method')
            d.clear(); await c.bot.send_message(chat_id=chat_id,text='❌ روش پرداخت کارت‌به‌کارت تنظیم نشده.',reply_markup=home(chat_id)); return
        d.clear(); d.update({'state':'awaiting_receipt','order_id':o['id']})
        delay=int(m.get('auto_approve_minutes') or 5)
        auto_line=f'\n🤖 تأیید خودکار فعال است؛ حداکثر {delay} دقیقه بعد از رسید بررسی می‌شود.' if m.get('auto_approve') else '\n👨‍💼 پرداخت پس از بررسی ادمین تأیید می‌شود.'
        await c.bot.send_message(chat_id=chat_id,text=f'💳 مبلغ قابل پرداخت: {money(card)}\n\nشماره کارت: {m["card_number"]}\nبه نام: {m["card_holder"]}{auto_line}\n\n📸 بعد از واریز، تصویر رسید را همینجا ارسال کنید.')
    else:
        d.clear(); ok=await approve_order(c.bot,o['id'],approved_by=chat_id)
        if ok: await c.bot.send_message(chat_id=chat_id,text='🟢 پرداخت از کیف پول انجام شد و درخواست شما در حال پردازش است.',reply_markup=home(chat_id))
        else: await c.bot.send_message(chat_id=chat_id,text='❌ پردازش سفارش انجام نشد؛ مبلغ رزرو شده در صورت خطا برگشت داده می‌شود.',reply_markup=home(chat_id))

async def order_summary(u,c):
    d=c.user_data
    panel_id=d.get('panel_id') or d.get('selected_panel_id')
    if not panel_id:
        await c.bot.send_message(chat_id=u.effective_user.id,text='❌ پنل انتخابی سفارش پیدا نشد. لطفاً خرید را از ابتدا شروع کنید.',reply_markup=home(u.effective_user.id))
        d.clear(); return
    d['panel_id']=panel_id
    p=get_panel(panel_id)
    if not p:
        await c.bot.send_message(chat_id=u.effective_user.id,text='❌ پنل انتخابی دیگر در دسترس نیست. لطفاً دوباره انتخاب کنید.',reply_markup=home(u.effective_user.id))
        d.clear(); return
    text=f'🛒 خلاصه سفارش\n\n🖥️ پنل: {p["name"]}\n'
    if d.get('kind')=='custom': text+=f'⚙️ نوع: پلن دلخواه\n📊 حجم: {vol(d.get("gb",0))}\n⏱ مدت: {duration(d.get("days",0))}\n'
    elif d.get('kind')=='renewal': text+=f'🛠 نوع عملیات: تمدید سرویس #{d.get("target_service_id")}\n⏱ مدت تمدید: {str(d.get("renew_months"))+" ماه" if d.get("renew_months") else str(d.get("custom_days",0))+" روز"}\n'
    else:
        pr=get_product(d['product_id']); text+=f'⭐ پلن: {pr["name"]}\n📊 حجم: {vol(pr["data_gb"])}\n⏱ مدت: {duration(pr["days"])}\n👥 تعداد یوزر: {pr["max_users"] or "نامحدود"}\n'
    text+=f'👤 Username: <code>{d["username"]}</code>\n💰 مبلغ نهایی: <b>{money(d["total"])}</b>\n\nاطلاعات صحیح است؟'
    coupon_btn=[B('🎟 اعمال کد تخفیف','apply_coupon','primary')] if not d.get('coupon_code') else [B('🎟 حذف کد تخفیف','remove_coupon','danger')]
    markup=KB([coupon_btn,[B('🟢 تأیید و پرداخت','confirm_checkout','success')],[B('✏️ تغییر Username','change_username'),B('🔙 لغو','cancel_checkout')]])
    if getattr(u,'message',None): await u.message.reply_text(text,parse_mode='HTML',reply_markup=markup)
    else: await c.bot.send_message(chat_id=u.effective_user.id,text=text,parse_mode='HTML',reply_markup=markup)

async def approve_order(bot,oid,approved_by=0):
    o=get_order(oid)
    if not o or o['status'] not in ('paid','pending_review'): return False
    p=get_panel(o['panel_id']); user=get_user(o['user_id'])
    if not p or not user: return False
    if not claim_for_processing(oid,approved_by): return False
    o=get_order(oid)
    try:
        api=PasarGuardAPI(api_base_url(p['url']),p['username'],p['password']); token=p.get('access_token')
        if not token:
            token=api.test_connection()['token']; update_panel(p['id'],'online',token)
        kind=o.get('kind') or 'suggested'
        if kind in ('renewal','volume_add'):
            sid=int(o.get('target_service_id') or 0)
            db=get_connection(); sr=db.execute('SELECT * FROM services WHERE id=? AND user_id=?',(sid,user['id'])).fetchone(); db.close()
            if not sr or sr['status']=='revoked': raise ValueError('سرویس هدف دیگر قابل استفاده نیست.')
            if kind=='renewal':
                add_days=int(o.get('custom_days') or 0)
                current=datetime.fromisoformat(sr['expires_at']).astimezone(timezone.utc) if sr['expires_at'] else now()
                if current<now(): current=now()
                new_exp=current+timedelta(days=add_days); api.update_admin(token,sr['pg_admin_id'],expire=int(new_exp.timestamp()))
                db=get_connection(); db.execute("UPDATE services SET expires_at=?,status='active' WHERE id=?",(new_exp.isoformat(),sid)); db.commit(); db.close()
                result_text=f'🔄 سرویس #{sid} با موفقیت {add_days} روز تمدید شد.'
            else:
                add_gb=int(o.get('custom_gb') or 0)
                current=int((api.get_admin_by_id(token,sr['pg_admin_id']) or {}).get('data_limit',0) or 0)
                if current==0: raise ValueError('این سرویس حجم نامحدود دارد و افزایش حجم برای آن امکان‌پذیر نیست.')
                api.update_admin(token,sr['pg_admin_id'],data_limit=current+add_gb*1024**3)
                result_text=f'➕ {add_gb} گیگ به سرویس #{sid} اضافه شد.'
            ts=now().isoformat(); set_order(oid,status='completed',approved_at=ts,approved_by=approved_by or 0,error=None); finalize_coupon(oid,True) if o.get('coupon_code') else None; audit('service_operation_completed',approved_by or 0,f'order={oid} kind={kind}')
            await bot.send_message(user['telegram_id'],result_text+f'\n\n🧾 سفارش #{oid}\n💰 مبلغ: {money(o["total_amount"])}',reply_markup=home(user['telegram_id']))
            return True
        gb=int(o.get('custom_gb',0) or 0); days=int(o.get('custom_days',0) or 0); max_users=int(o.get('custom_users',0) or 0)
        exp=0 if days<=0 else int((now()+timedelta(days=days)).timestamp())
        if o.get('product_id') and not reserve_product(o['product_id']): raise ValueError('ظرفیت فروش این پلن در همین لحظه تکمیل شده است.')
        result=api.create_admin(token,o['username'],o['password'],0 if gb==0 else gb*1024**3,exp,max_users)
        ts=now().isoformat(); set_order(oid,status='completed',approved_at=ts,approved_by=approved_by or 0,error=None); finalize_coupon(oid,True) if o.get('coupon_code') else None
        audit('order_approved',approved_by or 0,f'order={oid}'); await report_event(bot,'purchases',f'🟢 سفارش #{oid} تکمیل شد\n💰 مبلغ: {money(o["total_amount"])}\n👤 کاربر: @{o.get("telegram_username") or "-"}')
        db=get_connection(); db.execute('INSERT INTO services(order_id,user_id,panel_id,product_id,username,password,pg_admin_id,data_limit_bytes,status,started_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(oid,user['id'],p['id'],o.get('product_id'),o['username'],o['password'],result.get('id'),0 if gb==0 else gb*1024**3,'active',ts,None if exp==0 else datetime.fromtimestamp(exp,timezone.utc).isoformat())); db.commit(); db.close()
        await bot.send_message(user['telegram_id'],f'🎉 پنل شما آماده شد!\n\n🖥️ پنل: {p["name"]}\n🔗 لینک ورود: {customer_url(p["url"])}\n\n👤 Username: <code>{o["username"]}</code>\n🔑 Password: <code>{o["password"]}</code>\n📊 حجم: {vol(gb)}\n⏱ مدت: {duration(days)}\n\n⚠️ اطلاعات ورود را با شخص دیگری به اشتراک نگذارید.',parse_mode='HTML',reply_markup=KB([[B('🔗 ورود به پنل',f'login:{p["id"]}','primary')]]))
        return True
    except Exception as e:
        if o.get('product_id'): release_product(o['product_id'])
        if o.get('wallet_amount'): set_balance(o['user_id'],o['wallet_amount'],'refund','بازگشت رزرو کیف پول به علت خطای ساخت/عملیات سرویس',oid)
        if o.get('coupon_code'): finalize_coupon(oid,False)
        set_order(oid,status='error',error=str(e)[:1000]); audit('order_provision_error',approved_by or 0,f'order={oid} error={str(e)[:300]}'); log.exception('order operation failed')
        await bot.send_message(user['telegram_id'],f'❌ عملیات سفارش #{oid} با خطا مواجه شد. مبلغ رزرو کیف پول در صورت وجود برگشت داده شد.')
        return False

async def reject_order(bot,oid,admin_id):
    o=get_order(oid)
    if not o or o['status'] not in ('pending_review','awaiting_receipt'): return False
    if o.get('wallet_amount'): set_balance(o['user_id'],o['wallet_amount'],'refund','بازگشت مبلغ سفارش رد شده',oid)
    finalize_coupon(oid,False) if o.get('coupon_code') else None
    set_order(oid,status='rejected',rejected_at=now().isoformat(),rejected_by=admin_id)
    audit('order_rejected',admin_id,f'order={oid}'); await report_event(bot,'payments',f'🔴 پرداخت سفارش #{oid} رد شد\n💰 مبلغ: {money(o["total_amount"])}')
    user=get_user(o['user_id'])
    if user: await bot.send_message(user['telegram_id'],f'🔴 پرداخت سفارش #{oid} رد شد.\n\nمبلغ کیف پول ({money(o.get("wallet_amount",0))}) در صورت وجود به موجودی شما برگشت داده شد.')
    return True

def receipt_caption(o):
    username=f'@{o.get("username")}' if o.get('username') else '-'
    return (f'🧾 درخواست پرداخت جدید — سفارش #{o["id"]}\n\n'
            f'👤 کاربر تلگرام: @{o.get("telegram_username") or "-"}\n🆔 Telegram ID: {o["telegram_id"]}\n'
            f'🖥️ پنل: {o["panel_name"]}\n'
            f'📦 نوع سرویس: {"پلن پیشنهادی" if o.get("product_id") else "پلن دلخواه"}\n'
            f'📊 حجم: {vol(o.get('custom_gb',0))}\n'
            f'⏱ مدت: {duration(o.get('custom_days',0))}\n'
            f'👤 Username سرویس: {username}\n💰 مبلغ کل: {money(o["total_amount"])}\n'
            f'💰 از کیف پول: {money(o.get("wallet_amount",0))}\n💳 کارت‌به‌کارت: {money(o.get("card_amount",0))}\n\n'
            f'📌 درخواست کامل کاربر:\nحجم {vol(o.get('custom_gb',0))} / مدت {duration(o.get('custom_days',0))}\n'
            f'📸 رسید بالا قرار گرفته است.')

async def notify_admins_receipt(bot,o):
    markup=KB([[B('🟢 تأیید پرداخت',f'approve:{o["id"]}','success'),B('🔴 رد پرداخت',f'reject:{o["id"]}','danger')]])
    caption=receipt_caption(o)
    sent=False
    for aid in (list_admin_ids() if setting_bool('notify_admin_receipt',True) else []):
        try:
            msg=await bot.send_photo(aid,o['receipt_file_id'],caption=caption,reply_markup=markup)
            sent=True
            if not o.get('receipt_message_id'): set_order(o['id'],receipt_message_id=msg.message_id)
        except Exception as e:
            log.warning('admin receipt notify failed for %s: %s',aid,e)
    # Also send to the registered Topics report group when available, so a receipt is not lost
    # merely because an admin has not opened the bot chat.
    try:
        rc=get_reports_config(); topic_map=report_topics(); chat_id=rc.get('chat_id') if rc.get('enabled') and setting_bool('notify_report_receipt',True) else None
        thread_id=topic_map.get('payments') if chat_id else None
        if chat_id and thread_id:
            msg=await bot.send_photo(chat_id,o['receipt_file_id'],caption=caption,reply_markup=markup,message_thread_id=int(thread_id))
            sent=True
            if not o.get('receipt_message_id'): set_order(o['id'],receipt_message_id=msg.message_id)
    except Exception as e:
        log.warning('report receipt notify failed: %s',e)
    return sent

async def message(u,c):
    if not u.message:return
    x=u.effective_user; txt=(u.message.text or '').strip(); st=c.user_data.get('state') or ''
    usr=get_user_by_tid(x.id)
    if usr and is_blocked(usr['id']):
        await u.message.reply_text('🚫 حساب شما توسط مدیریت مسدود شده است.'); c.user_data.clear(); return
    try:
        if st=='username':
            if not valid_username(txt): raise ValueError('Username باید فقط شامل حروف انگلیسی و عدد باشد و حداکثر 32 کاراکتر داشته باشد.')
            c.user_data['username']=txt; c.user_data['state']='password'; c.user_data['pass_attempts']=0
            await u.message.reply_text('🔐 رمز عبور را وارد کنید.\n\nشرایط امنیتی: حداقل 12 کاراکتر، حداقل 2 حرف بزرگ، 2 حرف کوچک، 2 عدد و حداقل 1 نماد از !@#$%^&*\nمثال قوی: Ab7@xy92Klm!\n\nاگر نمی‌خواهید خودتان بسازید، دکمه 🎲 ساخت رمز رندوم را بزنید.',reply_markup=KB([[B('🎲 ساخت رمز رندوم','random_password','primary')]]))
        elif st=='password':
            if validpass(txt): c.user_data['password']=txt; await (order_summary(u,c) if setting_bool('order_summary',True) else checkout(u,c))
            else: await u.message.reply_text('❌ رمز شرایط امنیتی را ندارد.\nحداقل 12 کاراکتر + 2 حرف بزرگ + 2 حرف کوچک + 2 عدد + 1 نماد.\nیا از دکمه «🎲 ساخت رمز رندوم» استفاده کن.',reply_markup=KB([[B('🎲 ساخت رمز رندوم','random_password','primary')]]))
        elif st=='custom_gb':
            gb=int(txt); s=get_custom()
            if gb<0 or (gb and gb<s['min_gb']) or (s['max_gb'] and gb>s['max_gb']): raise ValueError('حجم خارج از محدوده است.')
            c.user_data['gb']=gb
            if not s.get('ask_duration',1):
                days=int(s.get('default_days',30) or 0); c.user_data['days']=days; c.user_data['users']=0; await finish_custom(u,c)
            else:
                c.user_data['state']='custom_days'; await show_custom_days(u,c)
        elif st=='custom_gb_custom':
            gb=int(txt); s=get_custom()
            if gb<=0 or gb<s['min_gb'] or (s['max_gb'] and gb>s['max_gb']): raise ValueError('حجم خارج از محدوده است.')
            c.user_data['gb']=gb
            if not s.get('ask_duration',1): c.user_data['days']=int(s.get('default_days',30) or 0); c.user_data['users']=0; await finish_custom(u,c)
            else: c.user_data['state']='custom_days'; await show_custom_days(u,c)
        elif st=='custom_months':
            months=int(txt);
            if months<=0 or months>120: raise ValueError('تعداد ماه باید بین 1 تا 120 باشد.')
            c.user_data['days']=months*30; c.user_data['users']=0; await finish_custom(u,c)
        elif st=='custom_months_custom':
            months=int(txt);
            if months<=0 or months>120: raise ValueError('تعداد ماه باید بین 1 تا 120 باشد.')
            c.user_data['days']=months*30; c.user_data['users']=0; await finish_custom(u,c)
        elif st=='custom_days':
            days=int(txt); s=get_custom()
            if days<0 or (days and days<s['min_days']) or (s['max_days'] and days>s['max_days']): raise ValueError('مدت خارج از محدوده است.')
            c.user_data['days']=days; c.user_data['users']=0; await finish_custom(u,c)
        elif st=='custom_days_custom':
            days=int(txt); s=get_custom()
            if days<=0 or days<s['min_days'] or (s['max_days'] and days>s['max_days']): raise ValueError('مدت خارج از محدوده است.')
            c.user_data['days']=days; c.user_data['users']=0; await finish_custom(u,c)
        elif st=='panel_name': c.user_data['panel_name']=txt;c.user_data['state']='panel_url';await u.message.reply_text('🔗 نام پنل ذخیره شد. حالا آدرس پنل را ارسال کنید.\n\n⚠️ توجه:\n🔸 آدرس پنل باید بدون `/dashboard` ارسال شود.\n🔹 اگر پورت پنل 443 است، پورت را وارد نکنید.\n🔸 اگر پنل روی پورت دیگری است، پورت را حتماً وارد کنید.\n🔹 آخر آدرس نباید `/` داشته باشد.\n🔸 در صورت وارد کردن IP، حتماً `http://` یا `https://` را نیز وارد کنید.\n💡 مثال: `https://example.com:8000`')
        elif st=='panel_url': c.user_data['panel_url']=api_base_url(txt);c.user_data['state']='panel_user';await u.message.reply_text('👤 حالا Username ادمین PasarGuard را ارسال کنید.\n\n⚠️ توجه:\n🔸 این حساب باید دسترسی ساخت و مدیریت ادمین داشته باشد.\n🔸 نام کاربری را دقیقاً مطابق پنل وارد کنید.\n💡 مثال: `ARM4N9`')
        elif st=='panel_user': c.user_data['panel_user']=txt;c.user_data['state']='panel_pass';await u.message.reply_text('🔐 حالا Password ادمین PasarGuard را ارسال کنید.\n\n⚠️ توجه:\n🔸 رمز باید متعلق به همان Username مرحله قبل باشد.\n🔸 این اطلاعات فقط برای اتصال ربات به API استفاده می‌شود.\n🔒 آن را داخل گزارش‌ها یا پیام‌های عمومی ارسال نکنید.')
        elif st=='panel_pass':
            d=c.user_data
            await u.message.reply_text('🔄 در حال بررسی اتصال به PasarGuard...')
            try:
                r=await asyncio.to_thread(PasarGuardAPI(d['panel_url'],d['panel_user'],txt).test_connection)
            except Exception as e:
                raise ValueError('اتصال به پنل موفق نبود؛ پنل ذخیره نشد.\n\n'+str(e)[:700])
            p=add_panel(d['panel_name'],d['panel_url'],d['panel_user'],txt); update_panel(p['id'],'online',r['token']); audit('panel_added',x.id,f'{d["panel_name"]} | connected'); await report_event(c.bot,'panels',f'🖥️ پنل جدید ثبت شد\n👤 ادمین: {x.id}\n📛 نام: {d["panel_name"]}')
            c.user_data.clear(); await u.message.reply_text('🟢 اتصال موفق بود و پنل با موفقیت ذخیره شد.',reply_markup=home(x.id))
        elif st=='prod_name': c.user_data['prod_name']=txt;c.user_data['state']='prod_gb';await u.message.reply_text('📊 حجم پلن را وارد کنید.\n\n⚠️ توجه:\n🔸 مقدار بر اساس گیگ وارد شود.\n🔸 برای حجم نامحدود عدد `0` وارد کنید.\n🔸 حجم و مدت نباید هر دو نامحدود باشند.\n💡 مثال: `500`')
        elif st=='prod_gb': c.user_data['prod_gb']=int(txt);c.user_data['state']='prod_days';await u.message.reply_text('📅 مدت اعتبار پلن را به روز وارد کنید.\n\n⚠️ توجه:\n🔸 مدت بر اساس روز محاسبه می‌شود.\n🔸 برای مدت نامحدود عدد `0` وارد کنید.\n💡 مثال: `30`')
        elif st=='prod_days': c.user_data['prod_days']=int(txt);c.user_data['state']='prod_users';await u.message.reply_text('👥 حداکثر تعداد کاربر قابل ساخت در این پلن را وارد کنید.\n\n⚠️ توجه:\n🔸 عدد `0` یعنی بدون محدودیت.\n💡 مثال: `10` یعنی حداکثر ۱۰ کاربر.')
        elif st=='prod_users': c.user_data['prod_users']=int(txt);c.user_data['state']='prod_price';await u.message.reply_text('💰 قیمت نهایی این پلن را به تومان وارد کنید.\n\n⚠️ توجه:\n🔸 فقط عدد وارد کنید.\n🔸 این مبلغ همان مبلغی است که کاربر برای خرید پلن می‌پردازد.\n💡 مثال: `850000`')
        elif st=='prod_price': c.user_data['prod_price']=int(txt);c.user_data['state']='prod_desc';await u.message.reply_text('📝 توضیحات پلن را وارد کنید.\n\n⚠️ این متن می‌تواند برای توضیح امکانات یا شرایط پلن به کاربر نمایش داده شود.\n💡 اگر توضیحی ندارید، فقط `-` ارسال کنید.')
        elif st=='prod_desc': c.user_data['prod_desc']='' if txt=='-' else txt;c.user_data['state']='prod_capacity';await u.message.reply_text('📦 ظرفیت فروش این پلن را مشخص کنید.\n\n⚠️ عدد `0` یعنی تعداد فروش نامحدود.\n🔸 اگر مثلاً `100` وارد کنید، بعد از ۱۰۰ فروش پلن از خرید خارج می‌شود.\n💡 مثال: `100`')
        elif st=='prod_capacity':
            d=c.user_data; cap=int(txt)
            if d['prod_gb']==0 and d['prod_days']==0: raise ValueError('حجم و زمان نمی‌توانند هر دو نامحدود باشند.')
            create_product(d['prod_name'],d['prod_gb'],d['prod_days'],d['prod_users'],d['prod_price'],d['prod_desc'],cap); audit('product_created',x.id,d['prod_name']); await report_event(c.bot,'products',f'📦 پلن جدید ساخته شد\n👤 ادمین: {x.id}\n📛 نام: {d["prod_name"]}\n💰 قیمت: {money(d["prod_price"])}'); c.user_data.clear(); await u.message.reply_text('🟢 پلن پیشنهادی ساخته شد.',reply_markup=home(x.id))
        elif st.startswith('custom_field:'):
            field=st.split(':',1)[1]; val=int(txt)
            if val<0: raise ValueError('عدد منفی مجاز نیست.')
            save_custom(**{field:val}); c.user_data.clear(); await u.message.reply_text('🟢 تنظیم ذخیره شد.',reply_markup=KB([[B('⚙️ تنظیم پلن دلخواه','custom_settings','primary')],[B('↩️ پلن‌ها','admin_products')]]))
        elif st=='card_number':
            n=''.join(ch for ch in txt if ch.isdigit())
            if len(n)!=16: raise ValueError('شماره کارت باید 16 رقم باشد.')
            c.user_data['card']=n;c.user_data['state']='card_holder';await u.message.reply_text('👤 نام صاحب کارت؟')
        elif st=='card_holder': c.user_data['holder']=txt;c.user_data['state']='card_auto';await u.message.reply_text('🤖 تأیید خودکار روشن باشد؟',reply_markup=KB([[B('🟢 روشن','card_auto:1','success'),B('⚪ خاموش','card_auto:0')]]))
        elif st=='card_auto': pass
        elif st=='card_minutes':
            minutes=int(txt)
            if minutes<1 or minutes>1440: raise ValueError('زمان باید بین 1 تا 1440 دقیقه باشد.')
            add_method(c.user_data['card'],c.user_data['holder'],True,minutes); c.user_data.clear(); await u.message.reply_text('🟢 کارت و تأیید خودکار ذخیره شد.',reply_markup=KB([[B('💰 مرکز مالی','admin_finance','primary')],[B('↩️ مدیریت','admin')]]))
        elif st=='auto_delay':
            minutes=int(txt)
            if minutes<1 or minutes>1440: raise ValueError('زمان باید بین 1 تا 1440 دقیقه باشد.')
            m=get_method()
            if m: add_method(m.get('card_number',''),m.get('card_holder',''),bool(m.get('auto_approve')),minutes); audit('auto_approve_delay',x.id,minutes)
            c.user_data.clear(); await u.message.reply_text('🟢 زمان تأیید خودکار ذخیره شد.',reply_markup=KB([[B('🤖 تأیید خودکار','auto_settings','primary')],[B('↩️ مالی','admin_finance')]]))
        elif st=='wallet_adjust':
            amount=int(txt)
            if amount<=0: raise ValueError('مبلغ باید بیشتر از صفر باشد.')
            uid=int(c.user_data['wallet_user_id']); sign=int(c.user_data['wallet_sign']); usr=get_user(uid)
            if not usr: raise ValueError('کاربر پیدا نشد.')
            if sign<0 and amount>int(usr.get('balance',0)): raise ValueError('موجودی برای این کاهش کافی نیست.')
            set_balance(uid,sign*amount,'admin_adjustment','تغییر موجودی توسط ادمین')
            audit('wallet_adjust',x.id,f'user={uid} delta={sign*amount}')
            c.user_data.clear(); await u.message.reply_text('🟢 موجودی کاربر با موفقیت تغییر کرد.',reply_markup=KB([[B('👤 اطلاعات کاربر','user:'+str(uid),'primary')],[B('↩️ مدیریت','admin')]]))
        elif st in ('service_renew','service_volume'):
            amount=int(txt)
            if amount<=0: raise ValueError('مقدار باید بیشتر از صفر باشد.')
            sid=int(c.user_data['service_id']); db=get_connection(); r=db.execute('SELECT s.*,p.url,p.username AS panel_user,p.password AS panel_pass FROM services s JOIN panels p ON p.id=s.panel_id WHERE s.id=?',(sid,)).fetchone(); db.close()
            if not r: raise ValueError('سرویس پیدا نشد.')
            pinfo=get_panel(r['panel_id']); api=PasarGuardAPI(api_base_url(r['url']),r['panel_user'],r['panel_pass']); token=pinfo.get('access_token') or api.test_connection()['token']
            if st=='service_renew':
                current=datetime.fromisoformat(r['expires_at']).astimezone(timezone.utc) if r['expires_at'] else now(); new_exp=current+timedelta(days=amount); api.update_admin(token,r['pg_admin_id'],expire=int(new_exp.timestamp()));
                db=get_connection(); db.execute("UPDATE services SET expires_at=?,status='active' WHERE id=?",(new_exp.isoformat(),sid)); db.commit(); db.close(); audit('service_renewed',x.id,f'service={sid} days={amount}'); msg='🔄 سرویس با موفقیت تمدید شد.'
            else:
                current=int((api.get_admin_by_id(token,r['pg_admin_id']) or {}).get('data_limit',0) or 0)
                if current==0: raise ValueError('این سرویس حجم نامحدود دارد و افزایش حجم برای آن معنی ندارد.')
                api.update_admin(token,r['pg_admin_id'],data_limit=current+amount*1024**3); msg='➕ حجم سرویس با موفقیت افزایش یافت.'; audit('service_volume_added',x.id,f'service={sid} gb={amount}')
            c.user_data.clear(); await u.message.reply_text(msg,reply_markup=home(x.id))
        elif st=='coupon_input':
            code=txt.strip().upper(); ok,info=coupon_available(code,get_user_by_tid(x.id)['id'])
            if not ok: raise ValueError(info)
            base=int(c.user_data.get('base_total',c.user_data.get('total',0))); cp=info; discount=(base*int(cp['value'])//100 if cp['kind']=='percent' else int(cp['value'])); discount=min(base,max(0,discount)); c.user_data['coupon_code']=code; c.user_data['discount_amount']=discount; c.user_data['base_total']=base; c.user_data['total']=base-discount; c.user_data['state']='ready'
            await order_summary(u,c);
        elif st=='wallet_topup_amount':
            amount=int(txt); minimum=int(get_setting('min_wallet_topup','100000') or 100000)
            if amount<minimum: raise ValueError(f'حداقل شارژ {money(minimum)} است.')
            uid=get_user_by_tid(x.id); db=get_connection(); cur=db.execute("INSERT INTO wallet_topups(user_id,amount,status) VALUES(?,?,?)",(uid['id'],amount,'awaiting_receipt')); db.commit(); tid=cur.lastrowid; db.close(); c.user_data.clear(); c.user_data.update({'state':'wallet_topup_receipt','topup_id':tid}); m=get_method()
            if not m: c.user_data.clear(); raise ValueError('روش کارت‌به‌کارت تنظیم نشده است.')
            await u.message.reply_text(f'💰 شارژ کیف پول\n\n💵 مبلغ: {money(amount)}\n💳 شماره کارت: {m["card_number"]}\n👤 به نام: {m["card_holder"]}\n\n📸 رسید پرداخت را همینجا ارسال کنید.')
        elif st=='service_renew_months':
            months=int(txt)
            if months<=0 or months>120: raise ValueError('تعداد ماه باید بین 1 تا 120 باشد.')
            sid=int(c.user_data['service_id']); uid=get_user_by_tid(x.id); price=months*int(get_custom().get('price_per_month',0) or 0)
            if price<=0: raise ValueError('قیمت ماهانه برای تمدید سرویس نامحدود تنظیم نشده است.')
            c.user_data.update({'kind':'renewal','target_service_id':sid,'custom_days':months*30,'renew_months':months,'base_total':price,'total':price,'state':'ready'}); await order_summary(u,c)
        elif st=='service_renew':
            days=int(txt);
            if days<=0 or days>3650: raise ValueError('مدت تمدید باید بین 1 تا 3650 روز باشد.')
            sid=int(c.user_data['service_id']); db=get_connection(); r=db.execute('SELECT * FROM services WHERE id=? AND user_id=?',(sid,get_user_by_tid(x.id)['id'])).fetchone(); db.close()
            if not r or r['status']=='revoked': raise ValueError('سرویس پیدا نشد.')
            price=days*int(get_custom().get('price_per_day',0) or 0)
            if price<=0: raise ValueError('قیمت هر روز برای تمدید تنظیم نشده است.')
            c.user_data.update({'kind':'renewal','target_service_id':sid,'custom_days':days,'base_total':price,'total':price,'state':'ready'}); await order_summary(u,c)
        elif st=='service_volume':
            gb=int(txt);
            if gb<=0 or gb>100000: raise ValueError('حجم افزایش باید بین 1 تا 100000 گیگ باشد.')
            sid=int(c.user_data['service_id']); db=get_connection(); r=db.execute('SELECT * FROM services WHERE id=? AND user_id=?',(sid,get_user_by_tid(x.id)['id'])).fetchone(); db.close()
            if not r or r['status']=='revoked': raise ValueError('سرویس پیدا نشد.')
            db=get_connection(); p=db.execute('SELECT * FROM panels WHERE id=?',(r['panel_id'],)).fetchone(); db.close();
            if not p: raise ValueError('پنل سرویس پیدا نشد.')
            price=gb*int(get_custom().get('price_per_gb',0) or 0)
            if price<=0: raise ValueError('قیمت هر گیگ برای افزایش حجم تنظیم نشده است.')
            c.user_data.update({'kind':'volume_add','target_service_id':sid,'custom_gb':gb,'base_total':price,'total':price,'panel_id':r['panel_id'],'state':'ready'}); await order_summary(u,c)
        elif st=='setting_value':
            key=c.user_data.get('setting_key'); save_setting(key,txt); c.user_data.clear()
            if key in ('support_text','support_username','support_link'):
                await u.message.reply_text('🟢 تنظیم پشتیبانی ذخیره شد.',reply_markup=KB([[B('💬 تنظیمات پشتیبانی','settings_support','primary')],[B('↩️ تنظیمات عمومی','admin_settings')]]))
            else:
                await u.message.reply_text('🟢 تنظیم ذخیره شد.',reply_markup=KB([[B('⚙️ تنظیمات عمومی','admin_settings','primary')]]))
        elif st=='search_user':
            rows=[[B(f"👤 {z['username'] or z['telegram_id']} | {z.get('balance',0):,}",f'user:{z["id"]}')] for z in list_users('all',txt)]; await u.message.reply_text('🔎 نتایج',reply_markup=KB(rows or [[B('📭 یافت نشد','noop')]]))
        elif st=='coupon_value':
            val=int(txt)
            if val<=0 or (c.user_data['coupon_kind']=='percent' and val>100): raise ValueError('مقدار تخفیف نامعتبر است.')
            c.user_data['coupon_value']=val;c.user_data['state']='coupon_max_users';await u.message.reply_text('👥 حداکثر چند نفر بتوانند استفاده کنند؟\n0 = نامحدود')
        elif st=='coupon_max_users': c.user_data['coupon_max_users']=int(txt);c.user_data['state']='coupon_per_user';await u.message.reply_text('👤 هر نفر چند بار بتواند استفاده کند؟')
        elif st=='coupon_per_user': c.user_data['coupon_per_user']=int(txt);c.user_data['state']='coupon_expiry';await u.message.reply_text('⏳ انقضا چند روز دیگر؟\n0 = بدون انقضا')
        elif st=='coupon_expiry': c.user_data['coupon_expiry']=int(txt);c.user_data['state']='coupon_code';await u.message.reply_text('🎟 حالا خودِ کد تخفیف را وارد کن:')
        elif st=='coupon_code':
            d=c.user_data; create_coupon(txt,d['coupon_kind'],d['coupon_value'],d['coupon_max_users'],d['coupon_per_user'],d['coupon_expiry']); c.user_data.clear(); await u.message.reply_text('🟢 کد تخفیف ساخته شد.',reply_markup=KB([[B('↩️ مرکز مالی','admin_finance')]]))
    except ValueError as e: await u.message.reply_text(f'❌ {e}\nدوباره وارد کن.')
    except Exception as e: log.exception('message error'); await u.message.reply_text(f'❌ خطا: {str(e)[:300]}')

async def finish_custom(u,c):
    d=c.user_data; total,_=custom_price(d['gb'],d['days'],0); d['total']=total; d['base_total']=total; d['discount_amount']=0; d['kind']='custom'; d['state']='username'
    price_note=(f'💰 قیمت ماهانه: {money(total // max(1, d["days"]//30))} تومان\n📅 مدت: {d["days"]//30} ماه\n💵 مبلغ کل: {money(total)}' if d['gb']==0 else ('💰 مبلغ فعلی: '+money(total)))
    text=f'✅ مشخصات سرویس ثبت شد.\n\n{price_note}\n\n👤 حالا Username پنل را وارد کنید.\nفقط حروف انگلیسی و عدد، بدون فاصله.\nمثال: Arman7429'
    markup=KB([[B('🎲 ساخت نام کاربری تصادفی','random_username','primary')]])
    if getattr(u,'message',None): await u.message.reply_text(text,reply_markup=markup)
    else: await c.bot.send_message(chat_id=u.effective_user.id,text=text,reply_markup=markup)


async def service_details(q, sid):
    db=get_connection(); r=db.execute('SELECT s.*,p.name panel_name,p.url,p.username AS panel_user,p.password AS panel_pass FROM services s JOIN panels p ON p.id=s.panel_id WHERE s.id=?',(sid,)).fetchone(); db.close()
    if not r or r['user_id']!=get_user_by_tid(q.from_user.id)['id']:
        await q.edit_message_text('❌ سرویس پیدا نشد.',reply_markup=home(q.from_user.id)); return
    text=(f'⚙️ مدیریت سرویس #{sid}\n\n🖥️ پنل: {r["panel_name"]}\n👤 Username: <code>{r["username"]}</code>\n'
          f'🟢 وضعیت: {r["status"]}\n📅 انقضا: {r["expires_at"] or "نامحدود"}\n🔗 {customer_url(r["url"])}')
    rows=[]
    if setting_bool('service_renewal_enabled',True): rows.append([B('🔄 تمدید سرویس',f'service_renew:{sid}','primary')])
    if setting_bool('service_volume_add_enabled',True): rows.append([B('➕ افزایش حجم',f'service_volume:{sid}','success')])
    if setting_bool('service_revoke_enabled',True): rows.append([B('⛔ لغو سرویس',f'service_revoke:{sid}','danger')])
    rows.append([B('🔗 لینک ورود',f'login:{r["panel_id"]}','primary'),B('↩️ پنل‌های من','my_panels')])
    await q.edit_message_text(text,parse_mode='HTML',reply_markup=KB(rows))

async def wallet_history(q):
    usr=get_user_by_tid(q.from_user.id); db=get_connection(); rows=db.execute('SELECT amount,type,description,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 30',(usr['id'],)).fetchall(); db.close()
    text='📜 تاریخچه کیف پول\n\n'+('\\n'.join(f'{money(r["amount"])} | {r["type"]} | {r["description"] or "-"} | {r["created_at"]}' for r in rows) if rows else '📭 تراکنشی ثبت نشده.')
    await q.edit_message_text(text,reply_markup=KB([[B('↩️ کیف پول','wallet')]]))

async def callback(u,c):
    q=u.callback_query; await q.answer(); data=q.data
    usr=get_user_by_tid(q.from_user.id)
    if usr and is_blocked(usr['id']) and not admin(q.from_user.id):
        await q.edit_message_text('🚫 حساب شما توسط مدیریت مسدود شده است.'); return
    if data=='home': await q.edit_message_text('منوی اصلی',reply_markup=home(q.from_user.id)); return
    if data=='admin' and admin(q.from_user.id): await admin_panel(q); return
    if not admin(q.from_user.id) and (data.startswith('admin') or data.startswith('approve:') or data.startswith('reject:') or data.startswith('panel_') or data.startswith('prod_') or data.startswith('custom_') or data.startswith('card_') or data.startswith('coupon_') or data.startswith('user:') or data.startswith('user_') or data.startswith('wallet_add:') or data.startswith('wallet_sub:') or data.startswith('settings_') or data.startswith('auto_') or data.startswith('set:') or data.startswith('toggle:') or data.startswith('topup_')): return
    if data=='confirm_restore':
        path=c.user_data.pop('pending_restore_path',None)
        if not path or not os.path.exists(path): await q.edit_message_text('❌ فایل بازیابی دیگر در دسترس نیست.'); return
        from database.core import DB_PATH
        backup=str(DB_PATH)+'.before-restore'
        try:
            if os.path.exists(backup): os.remove(backup)
            if os.path.exists(DB_PATH): os.replace(DB_PATH,backup)
            os.replace(path,DB_PATH); init_database(); audit('database_restored',q.from_user.id,'database restore completed'); await q.edit_message_text('🟢 دیتابیس با موفقیت بازیابی شد.\n\n💾 نسخه قبلی با پسوند before-restore نگه داشته شد.',reply_markup=KB([[B('⚙️ مدیریت','admin','primary')]]))
        except Exception as e: await q.edit_message_text('❌ بازیابی انجام نشد.\n'+str(e)[:500],reply_markup=KB([[B('↩️ مدیریت','admin')]]))
        finally:
            try:
                if os.path.exists(path): os.remove(path)
            except OSError: pass
        return
    if data=='cancel_restore':
        path=c.user_data.pop('pending_restore_path',None)
        if path and os.path.exists(path):
            try: os.remove(path)
            except OSError: pass
        await q.edit_message_text('⚪ بازیابی لغو شد.',reply_markup=KB([[B('⚙️ مدیریت','admin','primary')]])); return
    if data=='db_backup': await send_database_backup(c.bot,q.from_user.id); return
    if data=='admin_pending': await pending_orders(q); return
    if data=='admin_topups':
        db=get_connection(); rows=db.execute("SELECT t.id,t.amount,t.status,t.created_at,u.username,u.telegram_id FROM wallet_topups t JOIN users u ON u.id=t.user_id WHERE t.status='pending_review' ORDER BY t.id ASC LIMIT 50").fetchall(); db.close(); text='💰 شارژهای در انتظار\n\n'+('\n'.join(f'#{r["id"]} | @{r["username"] or "-"} | {money(r["amount"])} | {r["created_at"]}' for r in rows) if rows else '📭 موردی نیست.'); await q.edit_message_text(text,reply_markup=KB([[B('🔄 تازه‌سازی','admin_topups','primary')],[B('↩️ مدیریت','admin')]])); return
    if data=='admin_logs': await admin_logs(q); return
    if data=='admin_users': await users_menu(q); return
    if data.startswith('user:'): await user_details(q,int(data.split(':')[1])); return
    if data.startswith('user_services:'): await user_services(q,int(data.split(':')[1])); return
    if data.startswith('user_orders:'): await user_orders(q,int(data.split(':')[1])); return
    if data.startswith('user_wallet:'): await user_wallet(q,int(data.split(':')[1])); return
    if data.startswith('wallet_add:'):
        c.user_data.clear(); c.user_data.update({'state':'wallet_adjust','wallet_user_id':int(data.split(':')[1]),'wallet_sign':1}); await q.edit_message_text('➕ مبلغ افزایش موجودی را به تومان وارد کن:'); return
    if data.startswith('wallet_sub:'):
        c.user_data.clear(); c.user_data.update({'state':'wallet_adjust','wallet_user_id':int(data.split(':')[1]),'wallet_sign':-1}); await q.edit_message_text('➖ مبلغ کاهش موجودی را به تومان وارد کن:'); return
    if data.startswith('users:'):
        if data=='users:search': c.user_data.clear(); c.user_data['state']='search_user'; await q.edit_message_text('🔎 نام کاربری یا ID را بفرست:'); return
        await users_list(q,data.split(':')[1]); return
    if data=='admin_panels': await panels_menu(q); return
    if data=='panel_add': c.user_data.clear(); c.user_data['state']='panel_name'; await q.edit_message_text('➕ ابتدا نام پنل را ارسال کنید.\n\n⚠️ توجه:\n🔸 نام باید برای تشخیص پنل توسط ادمین و کاربر واضح باشد.\n🔸 بهتر است نام کشور یا لوکیشن داخل آن مشخص باشد.\n💡 مثال: Germany 🇩🇪'); return
    if data.startswith('panel:'):
        p=get_panel(int(data.split(':')[1])); await q.edit_message_text(f'🖥️ {p["name"]}\n🌐 {p["url"]}\n👤 {p["username"]}\n📡 {p["status"]}',reply_markup=KB([[B('🔄 تست اتصال','panel_test:'+str(p['id']),'primary'),B('🔴 حذف','panel_del:'+str(p['id']),'danger')],[B('↩️ بازگشت','admin_panels')]])); return
    if data.startswith('panel_test:'):
        p=get_panel(int(data.split(':')[1]))
        try: r=await asyncio.to_thread(PasarGuardAPI(api_base_url(p['url']),p['username'],p['password']).test_connection); update_panel(p['id'],'online',r['token']); await q.edit_message_text('🟢 اتصال موفق است.',reply_markup=KB([[B('↩️ پنل‌ها','admin_panels')]]))
        except Exception as e: update_panel(p['id'],'offline'); await q.edit_message_text('🔴 اتصال ناموفق\n'+str(e)[:500],reply_markup=KB([[B('↩️ پنل‌ها','admin_panels')]]))
        return
    if data.startswith('panel_del:'): delete_panel(int(data.split(':')[1])); await panels_menu(q); return
    if data=='admin_products': await products_menu(q); return
    if data=='prod_add': c.user_data.clear(); c.user_data['state']='prod_name'; await q.edit_message_text('📦 ابتدا نام پلن پیشنهادی را ارسال کنید.\n\n⚠️ توجه:\n🔸 نام باید کوتاه و قابل تشخیص باشد.\n🔸 بهتر است حجم و مدت داخل نام مشخص شود.\n💡 مثال: `500 گیگ | 30 روز | ویژه`'); return
    if data.startswith('prod:'):
        p=get_product(int(data.split(':')[1])); await q.edit_message_text(f'📦 {p["name"]}\n📊 {vol(p["data_gb"])}\n⏱ {duration(p["days"])}\n👥 {p["max_users"] or "نامحدود"}\n💰 {money(p["price"])}\n📦 ظرفیت: {p["capacity"] or "نامحدود"}\n\n{p["description"]}',reply_markup=KB([[B('🔄 فعال/غیرفعال','prod_toggle:'+str(p['id']),'primary')],[B('↩️ پلن‌ها','admin_products')]])); return
    if data.startswith('prod_toggle:'): toggle_product(int(data.split(':')[1])); await products_menu(q); return
    if data=='custom_settings': await custom_settings(q,c); return
    if data.startswith('custom_toggle:'): save_custom(enabled=int(data.endswith(':1'))); await custom_settings(q,c); return
    if data=='custom_ask_duration':
        s=get_custom(); save_custom(ask_duration=0 if s.get('ask_duration',1) else 1); await custom_settings(q,c); return
    if data.startswith('custom_field:'):
        field=data.split(':',1)[1]; c.user_data.clear(); c.user_data['state']=data
        prompts={
          'min_gb':'📊 حداقل حجم مجاز را به گیگ وارد کنید.\n\n⚠️ عدد مثبت وارد کنید.\n💡 مثال: `50`',
          'max_gb':'📊 حداکثر حجم مجاز را به گیگ وارد کنید.\n\n⚠️ عدد `0` یعنی بدون سقف.\n💡 مثال: `2000`',
          'price_per_gb':'💰 قیمت هر گیگ را به تومان وارد کنید.\n\n⚠️ برای سرویس‌های دارای حجم محدود استفاده می‌شود.\n💡 مثال: `1500`',
          'min_days':'📅 حداقل مدت مجاز را به روز وارد کنید.\n\n💡 مثال: `7`',
          'max_days':'📅 حداکثر مدت مجاز را به روز وارد کنید.\n\n⚠️ عدد `0` یعنی بدون سقف.',
          'price_per_day':'💰 قیمت هر روز را به تومان وارد کنید.\n\n⚠️ برای محاسبه سرویس‌های روزانه استفاده می‌شود.\n💡 مثال: `2000`',
          'price_per_month':'💰 قیمت ماهانه سرویس با حجم نامحدود را به تومان وارد کنید.\n\n⚠️ هر وقت کاربر «حجم نامحدود» انتخاب کند، قیمت بر اساس ماه محاسبه می‌شود و قیمت روزانه برای او استفاده نمی‌شود.\n🔸 این مبلغ قیمت ۱ ماه است و برای چند ماه در تعداد ماه ضرب می‌شود.\n💡 مثال: `500000`',
          'price_limited_unlimited':'💰 قیمت سرویس با حجم محدود و مدت نامحدود را وارد کنید.\n\n⚠️ اگر `0` باشد، قیمت بر اساس حجم محاسبه می‌شود.\n💡 مثال: `900000`',
          'default_days':'📌 مدت پیش‌فرض را به روز وارد کنید.\n\n⚠️ فقط وقتی «پرسیدن مدت» خاموش باشد استفاده می‌شود.\n💡 مثال: `30`'}
        await q.edit_message_text(prompts.get(field,'🔢 مقدار جدید را فقط به صورت عدد وارد کنید.')); return
    if data=='admin_finance': await finance(q); return
    if data=='card_setup': c.user_data.clear(); c.user_data['state']='card_number'; await q.edit_message_text('💳 شماره کارت دریافت وجه را وارد کنید.\n\n⚠️ دقیقاً ۱۶ رقم باشد و متعلق به کارت دریافت وجه شما باشد.\n🔸 فاصله و خط تیره مجاز است و ربات آن را پاک می‌کند.\n💡 مثال: `6037991234567890`'); return
    if data.startswith('card_auto:'):
        on=data.endswith(':1'); c.user_data['auto']=on
        if on: c.user_data['state']='card_minutes'; await q.edit_message_text('🤖 تأیید خودکار روشن شد.\n\n⏱ حالا مشخص کنید چند دقیقه بعد رسید به‌صورت خودکار تأیید شود.\n⚠️ عدد باید بین 1 تا 1440 دقیقه باشد.\n💡 مثال: `5`')
        else: add_method(c.user_data.get('card'),c.user_data.get('holder'),False,5); c.user_data.clear(); await finance(q)
        return
    if data=='coupon_setup': await q.edit_message_text('🎟 ابتدا نوع کد تخفیف را انتخاب کنید.\n\n⚠️ درصدی یعنی مثلاً ۲۰٪ تخفیف؛ مبلغی یعنی مثلاً ۱۰۰٬۰۰۰ تومان تخفیف.\n\nنوع کد را انتخاب کنید:',reply_markup=KB([[B('٪ تخفیف درصدی','coupon_kind:percent','primary')],[B('💵 تخفیف مبلغی','coupon_kind:fixed','primary')],[B('↩️ مالی','admin_finance')]])); return
    if data.startswith('coupon_kind:'): await coupon_kind(q,c); return
    if data=='admin_reports': await q.edit_message_text('📊 سیستم گزارشات\n\nبرای راه‌اندازی، یک گروه اختصاصی بسازید یا یک گروه موجود را انتخاب کنید.\n\n1️⃣ حالت Topics / انجمن گروه را فعال کنید.\n2️⃣ ربات را داخل همان گروه اضافه و Administrator کنید.\n3️⃣ نیازی به گرفتن یا ارسال آیدی گروه نیست.\n4️⃣ فقط دستور /register_reports را داخل همان گروه ارسال کنید.\n\n🤖 ربات خودش گروه را شناسایی می‌کند و تاپیک‌های کاربران، خریدها، پرداخت‌ها، پنل‌ها، کیف پول، پلن‌ها، ادمین‌ها، خطاها و سیستم را می‌سازد.',reply_markup=KB([[B('↩️ بازگشت','admin')]])); return
    if data=='admin_settings': await general_settings(q,c); return
    if data=='settings_text': await settings_text(q,c); return
    if data=='settings_payment': await settings_payment(q,c); return
    if data=='settings_purchase': await settings_purchase(q,c); return
    if data=='settings_notify': await settings_notify(q,c); return
    if data=='settings_support': await settings_support(q,c); return
    if data=='settings_security': await settings_security(q,c); return
    if data.startswith('toggle:'):
        key=data.split(':',1)[1]; save_setting(key,'0' if setting_bool(key,True) else '1'); await general_settings(q,c); return
    if data.startswith('auto_toggle:'):
        m=get_method();
        if m: add_method(m.get('card_number',''),m.get('card_holder',''),data.endswith(':1'),int(m.get('auto_approve_minutes') or 5)); audit('auto_approve_toggle',q.from_user.id,data.endswith(':1'))
        await auto_settings(q,c); return
    if data=='auto_delay': c.user_data.clear(); c.user_data['state']='auto_delay'; await q.edit_message_text('⏱ زمان تأیید خودکار را به دقیقه وارد کن.\nعدد بین 1 تا 1440:'); return
    if data.startswith('set:'):
        key=data.split(':',1)[1]; c.user_data.clear(); c.user_data['state']='setting_value'; c.user_data['setting_key']=key
        prompts={
            'support_text':'📝 متن پشتیبانی\n\nمتنی که کاربر هنگام ورود به بخش «💬 پشتیبانی» می‌بیند را وارد کنید.\n💡 مثال: برای دریافت راهنمایی با پشتیبانی در ارتباط باشید.',
            'support_username':'👤 Username پشتیبانی\n\nآیدی تلگرامی پشتیبانی را وارد کنید.\n💡 مثال: @ElevenSupport\n⚠️ این مورد فقط برای نمایش به کاربر است.',
            'support_link':'🔗 لینک پشتیبانی\n\nلینک مستقیم چت یا گروه پشتیبانی را وارد کنید.\n💡 مثال: https://t.me/ElevenSupport\n⚠️ لینک را کامل و بدون فاصله ارسال کنید.'
        }
        await q.edit_message_text(prompts.get(key,'✏️ مقدار جدید را بفرست:')); return
    if data=='buy_panel': await buy_start(q,c); return
    if data.startswith('buy_panel:'): await choose_panel(q,c,int(data.split(':')[1])); return
    if data=='buy_suggest': await suggested(q,c); return
    if data=='buy_custom': await custom_start(q,c); return
    if data.startswith('buy_prod:'):
        p=get_product(int(data.split(':')[1]));
        if not p or not p['enabled']: return
        if p['data_gb']==0 and p['days']==0: await q.edit_message_text('❌ این پلن همزمان حجم و زمان نامحدود دارد.'); return
        await after_plan(q,c,p['price'],'suggested',p,p['data_gb'],p['days'],p['max_users']); return
    if data=='random_username':
        name=randuser(); c.user_data['username']=name; c.user_data['state']='password'; c.user_data['pass_attempts']=0
        await q.edit_message_text(f'🎉 نام کاربری رندوم با موفقیت ساخته شد!\n\n👤 Username: <code>{name}</code>\n\nحالا رمز عبور را وارد کنید یا از دکمه ساخت رمز رندوم استفاده کنید.',parse_mode='HTML',reply_markup=KB([[B('🎲 ساخت رمز رندوم','random_password','primary')]])); return
    if data=='random_password':
        pw=randpass(); c.user_data['password']=pw
        await q.edit_message_text(f'🎉 رمز رندوم با موفقیت ثبت شد!\n\n🔑 رمز شما: <code>{pw}</code>\n\nاین رمز را در جای امن نگه دارید.',parse_mode='HTML',reply_markup=KB([[B('🟢 ادامه و نمایش خلاصه','show_summary','success')]])); return
    if data=='show_summary': await order_summary(u,c); return
    if data.startswith('custom_gb:'):
        gb=int(data.split(':')[1]); c.user_data['gb']=gb; s=get_custom()
        if not s.get('ask_duration',1): c.user_data['days']=int(s.get('default_days',30) or 0); c.user_data['users']=0; await finish_custom(u,c)
        else: c.user_data['state']='custom_days'; await show_custom_days(q,c)
        return
    if data=='custom_gb_custom': c.user_data['state']='custom_gb_custom'; await q.edit_message_text('✏️ حجم دلخواه را به گیگ وارد کنید.\nمثال: 430'); return
    if data.startswith('custom_months:'):
        months=int(data.split(':')[1])
        if months<=0 or months>120: await q.answer('تعداد ماه نامعتبر است.',show_alert=True); return
        c.user_data['days']=months*30; c.user_data['users']=0; await finish_custom(u,c); return
    if data=='custom_months_custom':
        c.user_data['state']='custom_months_custom'; await q.edit_message_text('✏️ تعداد ماه سرویس حجم نامحدود را وارد کنید.\n\n⚠️ چون حجم نامحدود است، قیمت به صورت ماهانه محاسبه می‌شود.\n🔸 عدد باید بین 1 تا 120 ماه باشد.\n💡 مثال: `3`'); return
    if data.startswith('custom_days:'):
        days=int(data.split(':')[1]); s=get_custom(); gb=int(c.user_data.get('gb',0) or 0)
        if days==0 and gb!=0 and int(s.get('price_limited_unlimited',0) or 0)<=0 and int(s.get('price_per_gb',0) or 0)<=0:
            await q.edit_message_text('❌ قیمت هر گیگ برای این حالت تنظیم نشده است.',reply_markup=KB([[B('↩️ انتخاب مدت','custom_days_back','primary')]])); return
        if days and (days<s['min_days'] or (s['max_days'] and days>s['max_days'])): await q.answer('این مدت خارج از محدوده است.',show_alert=True); return
        c.user_data['days']=days; c.user_data['users']=0; await finish_custom(u,c); return
    if data=='custom_days_custom': c.user_data['state']='custom_days_custom'; await q.edit_message_text('✏️ مدت دلخواه را به روز وارد کنید.\nمثال: 45'); return
    if data=='custom_days_back': await show_custom_days(q,c); return
    if data=='confirm_checkout': await checkout(u,c); return
    if data=='change_username': c.user_data['state']='username'; await q.edit_message_text('👤 Username جدید را وارد کن:'); return
    if data=='cancel_checkout': c.user_data.clear(); await q.edit_message_text('❌ سفارش لغو شد.',reply_markup=home(q.from_user.id)); return
    if data.startswith('approve:'):
        oid=int(data.split(':')[1]); ok=await approve_order(c.bot,oid,q.from_user.id); await q.edit_message_caption(caption=f'🟢 پرداخت سفارش #{oid} تأیید شد و سرویس در حال ساخت/ساخته شدن است.') if ok else await q.edit_message_caption(caption=f'⚠️ سفارش #{oid} قابل تأیید نیست یا قبلاً پردازش شده است.'); return
    if data.startswith('reject:'):
        oid=int(data.split(':')[1]); ok=await reject_order(c.bot,oid,q.from_user.id); await q.edit_message_caption(caption=f'🔴 پرداخت سفارش #{oid} رد شد.') if ok else await q.edit_message_caption(caption=f'⚠️ سفارش #{oid} قبلاً پردازش شده است.'); return
    if data.startswith('login:'):
        p=get_panel(int(data.split(':')[1])); await q.answer(); await q.message.reply_text(f'🔗 لینک ورود: {customer_url(p["url"])}'); return
    if data.startswith('copy_user:'):
        o=get_order(int(data.split(':')[1]));
        if o: await q.message.reply_text(f'👤 Username: <code>{o["username"]}</code>',parse_mode='HTML')
        return
    if data.startswith('copy_pass:'):
        o=get_order(int(data.split(':')[1]));
        if o: await q.message.reply_text(f'🔑 Password: <code>{o["password"]}</code>',parse_mode='HTML')
        return
    if data=='my_panels':
        usr=get_user_by_tid(q.from_user.id); db=get_connection(); rows=db.execute('SELECT s.*,p.name panel_name,p.url FROM services s JOIN panels p ON p.id=s.panel_id WHERE s.user_id=? ORDER BY s.id DESC',(usr['id'],)).fetchall(); db.close()
        if not rows: await q.edit_message_text('📭 هنوز پنلی نداری.',reply_markup=home(q.from_user.id)); return
        parts=[]
        for r in rows:
            parts.append(f'🖥️ {r["panel_name"]}\n👤 {r["username"]}\n🔑 {r["password"]}\n🟢 وضعیت: {r["status"]}\n🔗 {customer_url(r["url"])}')
        buttons=[]
        for r in rows: buttons.append([B(f'⚙️ مدیریت سرویس #{r["id"]}',f'service:{r["id"]}','primary')])
        buttons.append([B('↩️ منوی اصلی','home')])
        await q.edit_message_text('🖥️ پنل‌های من\n\n'+'\n\n'.join(parts),reply_markup=KB(buttons)); return
    if data.startswith('service:'):
        await service_details(q,int(data.split(':')[1])); return
    if data=='wallet_history':
        await wallet_history(q); return
    if data.startswith('service_renew:') or data.startswith('service_volume:') or data.startswith('service_revoke:'):
        sid=int(data.split(':')[1]); db=get_connection(); r=db.execute('SELECT s.*,p.name panel_name FROM services s JOIN panels p ON p.id=s.panel_id WHERE s.id=?',(sid,)).fetchone(); db.close()
        if not r: await q.answer('سرویس پیدا نشد.',show_alert=True); return
        if data.startswith('service_revoke:'):
            await q.edit_message_text(f'⚠️ لغو سرویس #{sid}\n\nاین عملیات سرویس را در پنل PasarGuard حذف/غیرفعال می‌کند و قابل برگشت خودکار نیست.\n\nبرای تأیید دوباره دکمه زیر را بزنید.',reply_markup=KB([[B('🔴 تأیید لغو',f'confirm_revoke:{sid}','danger')],[B('↩️ بازگشت',f'service:{sid}')]])); return
        state='service_renew' if data.startswith('service_renew:') else 'service_volume'
        unlimited=(int(r['data_limit_bytes'] or 0)==0) if 'data_limit_bytes' in r.keys() else False
        actual_state='service_renew_months' if state=='service_renew' and unlimited else state
        c.user_data.clear(); c.user_data.update({'state':actual_state,'service_id':sid,'panel_id':r['panel_id'],'selected_panel_id':r['panel_id'],'username':r['username'],'password':r['password']})
        if actual_state=='service_renew_months': prompt='🔄 تمدید سرویس حجم نامحدود\n\n⏱ تعداد ماه را وارد کنید.\n⚠️ بین 1 تا 120 ماه\n💰 قیمت بر اساس قیمت ماهانه تنظیم‌شده توسط ادمین محاسبه می‌شود.\n💡 مثال: `3`'
        elif state=='service_renew': prompt='🔄 مدت تمدید را به روز وارد کنید.\n\n⚠️ فقط عدد مثبت وارد کنید.\n💡 مثال: `30`'
        else: prompt='➕ مقدار حجم اضافه را به گیگ وارد کنید.\n\n⚠️ فقط عدد مثبت وارد کنید.\n💡 مثال: `100`'
        await q.edit_message_text(prompt); return
    if data.startswith('confirm_revoke:'):
        sid=int(data.split(':')[1]); db=get_connection(); r=db.execute('SELECT s.*,p.url,p.username AS panel_user,p.password AS panel_pass FROM services s JOIN panels p ON p.id=s.panel_id WHERE s.id=?',(sid,)).fetchone(); db.close()
        if not r: return
        try:
            api=PasarGuardAPI(api_base_url(r['url']),r['panel_user'],r['panel_pass']); token=get_panel(r['panel_id']).get('access_token') or api.test_connection()['token']; api.delete_admin(token,r['pg_admin_id']);
            db=get_connection(); db.execute("UPDATE services SET status='revoked' WHERE id=?",(sid,)); db.commit(); db.close(); audit('service_revoked',q.from_user.id,f'service={sid}'); await q.edit_message_text('🟢 سرویس لغو شد.',reply_markup=home(q.from_user.id))
        except Exception as e: await q.edit_message_text('❌ لغو سرویس ناموفق بود.\n'+str(e)[:500],reply_markup=KB([[B('↩️ سرویس',f'service:{sid}')]]))
        return
    if data=='apply_coupon':
        c.user_data['state']='coupon_input'; await q.edit_message_text('🎟 کد تخفیف را وارد کنید.\n\n⚠️ کد را دقیقاً وارد کنید.\n💡 مثال: ELEVEN20'); return
    if data=='remove_coupon':
        c.user_data.pop('coupon_code',None); c.user_data['discount_amount']=0; c.user_data['total']=int(c.user_data.get('base_total',c.user_data.get('total',0))); await order_summary(u,c); return
    if data=='wallet_topup':
        m=get_method()
        if not m: await q.edit_message_text('❌ روش کارت‌به‌کارت برای شارژ کیف پول تنظیم نشده است.',reply_markup=KB([[B('↩️ کیف پول','wallet')]])); return
        c.user_data.clear(); c.user_data['state']='wallet_topup_amount'; minimum=int(get_setting('min_wallet_topup','100000') or 100000); await q.edit_message_text(f'💰 شارژ کیف پول\n\nحداقل مبلغ شارژ: {money(minimum)}\n\n⚠️ فقط عدد تومان وارد کنید.\n💡 مثال: `500000`'); return
    if data.startswith('topup_approve:') or data.startswith('topup_reject:'):
        tid=int(data.split(':')[1]); db=get_connection(); t=db.execute('SELECT * FROM wallet_topups WHERE id=?',(tid,)).fetchone(); db.close()
        if not t or t['status']!='pending_review': await q.answer('این درخواست قبلاً پردازش شده است.',show_alert=True); return
        if data.startswith('topup_approve:'):
            result=approve_topup(tid,q.from_user.id)
            if not result: await q.answer('این درخواست قبلاً پردازش شده است.',show_alert=True); return
            audit('wallet_topup_approved',q.from_user.id,f'topup={tid}'); await report_event(c.bot,'wallet',f'🟢 شارژ کیف پول #{tid} تأیید شد\n💰 مبلغ: {money(result["amount"])}'); usr=get_user(result['user_id']); await q.edit_message_caption(caption=f'🟢 شارژ #{tid} تأیید شد\n\n💵 مبلغ: {money(result["amount"])}'); await c.bot.send_message(usr['telegram_id'],f'💰 شارژ کیف پول شما تأیید شد.\n\n➕ مبلغ: {money(result["amount"])}\n💳 موجودی جدید: {money(usr.get("balance",0))}'); return
        result=reject_topup(tid,q.from_user.id)
        if not result: await q.answer('این درخواست قبلاً پردازش شده است.',show_alert=True); return
        audit('wallet_topup_rejected',q.from_user.id,f'topup={tid}'); await report_event(c.bot,'wallet',f'🔴 شارژ کیف پول #{tid} رد شد\n💰 مبلغ: {money(result["amount"])}'); usr=get_user(result['user_id']); await q.edit_message_caption(caption=f'🔴 شارژ #{tid} رد شد'); await c.bot.send_message(usr['telegram_id'],f'🔴 درخواست شارژ کیف پول #{tid} رد شد.'); return
    if data=='wallet':
        usr=get_user_by_tid(q.from_user.id); await q.edit_message_text(f'💰 کیف پول\n\nموجودی: {money(usr.get("balance",0))}',reply_markup=KB([[B('➕ شارژ کیف پول','wallet_topup','success')],[B('📜 تاریخچه تراکنش‌ها','wallet_history','primary')],[B('↩️ منوی اصلی','home')]])); return
    if data=='account':
        usr=get_user_by_tid(q.from_user.id); await q.edit_message_text(f'👤 حساب من\n\nID: {usr["telegram_id"]}\nUsername: @{usr["username"] or "-"}\nموجودی: {money(usr.get("balance",0))}',reply_markup=home(q.from_user.id)); return
    if data=='support':
        txt=setting_text('support_text','💬 برای پشتیبانی با ادمین در ارتباط باشید.')
        username=get_setting('support_username','').strip(); link=get_setting('support_link','').strip()
        rows=[]
        if link: rows.append([U('🔗 ارتباط با پشتیبانی',link)])
        extra=(f'\n\n👤 پشتیبانی: {username}' if username else '')
        if link: extra += f'\n🔗 {link}'
        await q.edit_message_text(txt+extra,reply_markup=KB(rows+[[B('↩️ منوی اصلی','home')]])); return
    if data=='noop': return

def set_topup_receipt(tid,fid):
    db=get_connection(); db.execute("UPDATE wallet_topups SET receipt_file_id=?,status='pending_review' WHERE id=? AND status='awaiting_receipt'",(fid,tid)); db.commit(); db.close()

def topup_info(tid):
    db=get_connection(); r=db.execute('SELECT t.*,u.telegram_id,u.username,u.first_name FROM wallet_topups t JOIN users u ON u.id=t.user_id WHERE t.id=?',(tid,)).fetchone(); db.close(); return dict(r) if r else None

async def notify_topup_admins(bot,tid):
    t=topup_info(tid);
    if not t:return
    caption=(f'💰 درخواست شارژ کیف پول — #{tid}\n\n👤 کاربر: @{t.get("username") or "-"}\n🆔 Telegram ID: {t["telegram_id"]}\n💵 مبلغ: {money(t["amount"])}\n\n📸 رسید بالا قرار گرفته است.')
    kb=KB([[B('🟢 تأیید شارژ',f'topup_approve:{tid}','success'),B('🔴 رد شارژ',f'topup_reject:{tid}','danger')]])
    for aid in list_admin_ids():
        try: await bot.send_photo(aid,t['receipt_file_id'],caption=caption,reply_markup=kb)
        except Exception as e: log.warning('topup notify failed: %s',e)

async def photo_handler(u,c):
    state=c.user_data.get('state')
    if state=='wallet_topup_receipt':
        tid=c.user_data.get('topup_id'); db=get_connection(); top=db.execute('SELECT * FROM wallet_topups WHERE id=?',(tid,)).fetchone(); db.close()
        if not top or top['status']!='awaiting_receipt': c.user_data.clear(); await u.message.reply_text('❌ درخواست شارژ پیدا نشد یا قبلاً پردازش شده است.'); return
        fid=u.message.photo[-1].file_id; set_topup_receipt(tid,fid)
        await notify_topup_admins(c.bot,tid)
        c.user_data.clear(); await u.message.reply_text('📸 رسید شارژ ثبت و برای ادمین ارسال شد.\n⏳ پس از تأیید، مبلغ به کیف پول اضافه می‌شود.')
        return
    if state!='awaiting_receipt': return
    oid=c.user_data.get('order_id'); o=get_order(oid)
    if not o or o['status']!='awaiting_receipt': await u.message.reply_text('❌ سفارش پیدا نشد یا قبلاً پردازش شده است.'); c.user_data.clear(); return
    m=get_method(); ts=now(); auto_at=ts+timedelta(minutes=int(m.get('auto_approve_minutes',5))) if m and m.get('auto_approve') else None
    fid=u.message.photo[-1].file_id; set_order(oid,status='pending_review',receipt_at=ts.isoformat(),receipt_file_id=fid,auto_approve_at=auto_at.isoformat() if auto_at else None); audit('receipt_received',u.effective_user.id,f'order={oid}')
    fresh=get_order(oid); delivered=await notify_admins_receipt(c.bot,fresh); c.user_data.clear()
    if auto_at: await u.message.reply_text(f'📸 رسید ثبت شد.\n🤖 تأیید خودکار فعال است و حداکثر تا {m.get("auto_approve_minutes",5)} دقیقه دیگر بررسی می‌شود.')
    else: await u.message.reply_text('📸 رسید ثبت شد و برای ادمین ارسال شد.\n⏳ پرداخت در انتظار بررسی است.' if delivered else '📸 رسید ثبت شد، اما ارسال آن به ادمین انجام نشد.')

async def auto_job(app):
    while True:
        try:
            for o in list_pending():
                if o['status']=='pending_review' and o.get('auto_approve_at'):
                    try: due=datetime.fromisoformat(o['auto_approve_at'])
                    except Exception: continue
                    if due<=now():
                        await approve_order(app.bot,o['id'],0)
        except Exception: log.exception('auto approval job')
        await asyncio.sleep(10)

async def post_init(app): app.create_task(auto_job(app))

async def report_event(bot,topic_key,text,photo_file_id=None):
    try:
        rc=get_reports_config(); topics=report_topics(); chat_id=rc.get('chat_id') if rc.get('enabled') else None; thread=topics.get(topic_key) if chat_id else None
        if not chat_id or not thread:return False
        if photo_file_id: await bot.send_photo(chat_id,photo_file_id,caption=text,message_thread_id=int(thread))
        else: await bot.send_message(chat_id,text,message_thread_id=int(thread))
        return True
    except Exception as e: log.warning('report event failed: %s',e); return False

async def register_reports(u,c):
    if not admin(u.effective_user.id) or not u.effective_chat or u.effective_chat.type not in ('group','supergroup'):
        return
    rc=get_reports_config()
    if rc.get('enabled') and rc.get('chat_id')==u.effective_chat.id:
        await u.message.reply_text('🟢 این گروه قبلاً ثبت شده است.\n\nاگر تاپیک‌ها وجود دارند، نیازی به اجرای دوباره دستور نیست.'); return
    names={'users':'👤 کاربران','purchases':'🛒 خریدها','payments':'💳 پرداخت‌ها','panels':'🖥️ پنل‌ها','wallet':'💰 کیف پول','products':'📦 محصولات','admins':'👑 ادمین','errors':'⚠️ خطاها','system':'⚙️ سیستم'}; topics={}
    try:
        for k,n in names.items():
            r=await c.bot.create_forum_topic(u.effective_chat.id,n); topics[k]=r.message_thread_id
        save_reports(u.effective_chat.id,topics); audit('reports_registered',u.effective_user.id,f'chat={u.effective_chat.id}')
        await u.message.reply_text('🟢 گروه گزارشات با موفقیت ثبت شد!\n\n🆔 گروه به‌صورت خودکار شناسایی شد.\n📊 ۹ تاپیک گزارشات ساخته شد.\n\nاز این به بعد گزارش‌های ربات در تاپیک مربوطه ارسال می‌شوند.\n\n💡 برای این دستور نیازی به گرفتن یا ارسال آیدی گروه نبود؛ فقط کافی بود ربات ادمین گروه باشد و دستور را داخل همان گروه بفرستید.')
    except Exception as e:
        await u.message.reply_text('❌ ثبت گروه گزارشات کامل نشد.\n\n⚠️ مطمئن شوید ربات Administrator است و Topics فعال است.\n\nجزئیات خطا:\n'+str(e)[:700])

async def error(u,c): log.exception('update error',exc_info=c.error)
def main():
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build(); app.add_handler(CommandHandler('start',start)); app.add_handler(CommandHandler('register_reports',register_reports)); app.add_handler(CallbackQueryHandler(callback)); app.add_handler(MessageHandler(filters.Document.ALL,restore_database_from_telegram)); app.add_handler(MessageHandler(filters.PHOTO,photo_handler)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,message)); app.add_error_handler(error); print('Starting bot...'); app.run_polling()
if __name__=='__main__': main()
