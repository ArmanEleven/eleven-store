

def normalize_panel_url(value):
    value=(value or "").strip()
    if not value: raise ValueError("آدرس پنل وارد نشده است.")
    if value.lower() in {"germany","iran","turkey","dubai","uae","oman","emirates"}: raise ValueError("آدرس پنل باید مثل https://IP:PORT یا دامنه باشد.")
    if not re.match(r"^https?://",value,re.I): value="https://"+value
    from urllib.parse import urlparse
    if not urlparse(value).netloc: raise ValueError("آدرس پنل معتبر نیست.")
    return value.rstrip("/")

TRIAL_DEFAULTS={"duration_minutes":120,"volume_gb":5}
def trial_duration_label(minutes):
    minutes=int(minutes)
    return f"{minutes//1440} روزه" if minutes%1440==0 else (f"{minutes//60} ساعته" if minutes%60==0 else f"{minutes} دقیقه‌ای")
import asyncio, os, re, sys, uuid, shutil, sqlite3, tempfile, logging, json, base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from config import BOT_TOKEN, OWNER_ID, APP_NAME
from database.core import init_database, get_connection
from database.users import upsert_user, get_user_by_tid, get_user, list_users, set_balance, is_blocked, set_blocked
from database.products import list_products, get_product, create_product, toggle_product, update_product, delete_product
from database.finance import add_method, list_methods, get_method, set_default_method
from database.support import get_open_ticket, create_ticket, get_ticket, close_ticket, add_message, list_messages, list_open_tickets

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log=logging.getLogger('eleven-store')
BASE=Path(__file__).resolve().parent
TEMPLATE=BASE/'customer_template'
INSTANCES=BASE/'instances'; INSTANCES.mkdir(exist_ok=True)
PLANS={
 '1m':('لایسنس ۱ ماهه',250_000,30),
 '2m':('لایسنس ۲ ماهه',500_000,60),
 '3m':('لایسنس ۳ ماهه',699_000,90),
}
PROCESSES={}
STORE_BOT_ID=None  # filled at startup from BOT_TOKEN's own getMe(), used to block token reuse (rule #8/#9)
SECTION_HELP={
 'a_users':'👥 کاربران\n\nاز این بخش می‌توانید هر کاربر را با شناسه عددی (ID) تلگرام جستجو کنید، اطلاعات کامل او (نام کاربری، تاریخ عضویت، موجودی، سفارش‌ها، تراکنش‌ها، ربات‌ها و لایسنس‌ها) را ببینید، موجودی کیف پولش را افزایش/کاهش دهید، Admin ID او را تغییر دهید یا او را مسدود/رفع مسدودی کنید.',
 'a_bots':'🤖 ربات‌ها\n\nلیست تمام Instanceهای مشتریان (ربات‌های فروش پنل) به همراه وضعیت اجرا (active/stopped/error) و لایسنس مربوطه.',
 'a_licenses':'📦 لایسنس‌ها\n\nجمع‌بندی تعداد لایسنس‌های فروخته‌شده به تفکیک نوع پلن.',
 'a_payments':'💳 پرداخت‌ها\n\nلیست سفارش‌های ثبت‌شده (خرید لایسنس) و وضعیت هرکدام (در انتظار رسید/در انتظار بررسی/تأیید/رد).',
 'a_wallets':'💰 کیف پول‌ها\n\nجمع کل موجودی کیف پول تمام کاربران. برای شارژ/کسر موجودی یک کاربر خاص، از بخش «👥 کاربران» استفاده کنید.',
 'a_referrals':'🎁 زیرمجموعه‌ها\n\nوضعیت سیستم دعوت زیرمجموعه و پاداش‌های تعریف‌شده.',
 'a_backups':'💾 بکاپ‌ها\n\nلیست آخرین بکاپ‌های SQL گرفته‌شده از Instanceهای مشتریان (دستی، دوره‌ای، هنگام انقضا یا قبل از حذف).',
 'a_support':'🆘 پشتیبانی\n\nتیکت‌های باز کاربران؛ برای پاسخ به هر تیکت، روی پیام ارسالی از سمت کاربر و دکمه «🔵 پاسخ» بزنید.',
 'a_products':'🛒 محصولات\n\nمدیریت کامل پلن‌های لایسنس Eleven Store: افزودن، ویرایش، فعال/غیرفعال‌کردن و حذف محصول. هر محصول شامل نام، قیمت، حجم، مدت، حداکثر کاربر، ظرفیت فروش و توضیحات است؛ حجم و مدت مستقل‌اند و فقط یکی می‌تواند نامحدود باشد.',
 'a_texts':'✏️ مدیریت متن‌ها\n\nمتن‌های مهم ربات (خوش‌آمدگویی، پشتیبانی و…) را می‌توانید مستقیماً از همینجا ویرایش کنید، بدون نیاز به دسترسی به کد یا سرور.',
 'a_cards':'💳 کارت‌های بانکی\n\nکارت(های) مقصد برای واریز مشتریان؛ کاربران رسید واریز به این کارت را ارسال می‌کنند.',
 'a_reports':'📊 گزارش‌ها\n\nآمار کلی ربات‌ها و سفارش‌ها.',
 'a_settings':'⚙️ تنظیمات\n\nوضعیت کلی سرویس‌های Eleven Store (بکاپ خودکار، بررسی انقضا و غیره). توکن‌ها و اطلاعات حساس اینجا نمایش داده نمی‌شوند.',
}
init_database()

# ---------- helpers ----------
def now(): return datetime.now(timezone.utc)
def money(n): return f'{int(n):,} تومان'
def btn(t,d,style='primary'): return InlineKeyboardButton(t,callback_data=d,style=style)
def kb(rows): return InlineKeyboardMarkup(rows)
def admin(uid):
    return uid==OWNER_ID

def _fernet():
    key=os.getenv('TOKEN_ENCRYPTION_KEY','').strip()
    if not key: return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception as e: raise RuntimeError('TOKEN_ENCRYPTION_KEY نامعتبر است یا cryptography نصب نیست.') from e

def protect_token(token):
    f=_fernet()
    return 'fernet1:'+f.encrypt(token.encode()).decode() if f else token

def reveal_token(value):
    if not value: return value
    if value.startswith('fernet1:'):
        f=_fernet()
        if not f: raise RuntimeError('TOKEN_ENCRYPTION_KEY برای رمزگشایی توکن Instance تنظیم نشده است.')
        return f.decrypt(value[8:].encode()).decode()
    return value

def audit(action, admin_id=0, details=''):
    try:
        c=get_connection(); c.execute('INSERT INTO admin_logs(admin_id,action,details) VALUES(?,?,?)',(admin_id,action,details)); c.commit(); c.close()
    except Exception: pass

def atomic_wallet_hold(user_id, amount, order_id):
    c=get_connection()
    try:
        c.execute('BEGIN IMMEDIATE')
        r=c.execute('SELECT balance FROM users WHERE id=?',(user_id,)).fetchone()
        if not r or int(r['balance'])<int(amount): c.rollback(); return False
        c.execute('UPDATE users SET balance=balance-? WHERE id=? AND balance>=?',(amount,user_id,amount))
        if c.total_changes < 1: c.rollback(); return False
        c.execute("INSERT INTO transactions(user_id,amount,type,description,order_id) VALUES(?,?,?,?,?)",(user_id,-amount,'license_purchase','رزرو مبلغ خرید لایسنس',order_id))
        c.commit(); return True
    except Exception:
        c.rollback(); raise
    finally: c.close()

def refund_wallet_once(user_id, amount, order_id, reason):
    if not amount: return False
    c=get_connection()
    try:
        c.execute('BEGIN IMMEDIATE')
        exists=c.execute("SELECT 1 FROM transactions WHERE user_id=? AND order_id=? AND type='order_refund' LIMIT 1",(user_id,order_id)).fetchone()
        if exists: c.rollback(); return False
        c.execute('UPDATE users SET balance=balance+? WHERE id=?',(amount,user_id))
        c.execute("INSERT INTO transactions(user_id,amount,type,description,order_id) VALUES(?,?,?,?,?)",(user_id,amount,'order_refund',reason,order_id))
        c.commit(); return True
    except Exception:
        c.rollback(); raise
    finally: c.close()


async def edit_callback_message(q, text, **kwargs):
    """Edit callback message whether it is text, photo, or document media."""
    msg = q.message
    if msg is not None and (msg.photo or msg.document):
        return await q.edit_message_caption(caption=text, **kwargs)
    return await q.edit_message_text(text, **kwargs)

def setting(key, default=''):
    c=get_connection(); r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); c.close(); return r['value'] if r else default

def save_setting(key,value):
    c=get_connection(); c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value))); c.commit(); c.close()

def ensure_products():
    if not list_products(False):
        for k,(name,price,days) in PLANS.items():
            create_product(name,0,days,0,price,f'لایسنس ربات فروش پنل برای {days} روز',0)

def active_plans():
    """Products (license plans) as configured live from the admin panel — DB is the source of truth."""
    return [p for p in list_products(True) if int(p.get('days') or 0) > 0]

def get_plan(key):
    """Resolve a plan key to (name, price, days).
    Supports both new DB-backed products (key='p<id>') and legacy hard-coded
    plan keys ('1m'/'2m'/'3m') already stored on old bots/orders rows, so
    existing licenses keep working even after the product catalog changes."""
    if isinstance(key,str) and key.startswith('p'):
        try: pid=int(key[1:])
        except ValueError: pid=None
        if pid is not None:
            p=get_product(pid)
            if p: return p['name'],int(p['price']),int(p['days'] or 0)
    if key in PLANS: return PLANS[key]
    return None

def user_row(tid):
    x=get_user_by_tid(tid)
    return x or upsert_user(tid,'','')

def home(tid):
    rows=[[btn('🛒 تهیه اشتراک','build','success')],[btn('🎁 دریافت تست رایگان ۲ ساعته','trial_start','success')],[btn('📦 اشتراک‌های من','bots','primary')],[btn('💰 کیف پول','wallet')],[btn('🎁 دعوت دوستان','referral')],[btn('⚙️ حساب کاربری','account')]]
    if admin(tid): rows.append([btn('👑 پنل ادمین','admin','primary')])
    return kb(rows)

def license_text(b):
    exp=b.get('expires_at') or 'نامحدود'
    return (f'🤖 ربات: @{b.get("bot_username") or "-"}\n🟢 وضعیت: {b["status"]}\n'
            f'📦 لایسنس: {b["plan_name"]}\n🆔 Admin ID: {b["admin_id"]}\n'
            f'📅 انقضا: {exp}\n💾 آخرین بکاپ: {b.get("last_backup_at") or "-"}')

# ---------- child bot manager ----------
def instance_env(bot_token, admin_id):
    env=os.environ.copy(); env.update({'BOT_TOKEN':bot_token,'OWNER_ID':str(admin_id),'ADMIN_ID':str(admin_id),'PYTHONUNBUFFERED':'1'}); return env

def validate_token(token):
    r=requests.get(f'https://api.telegram.org/bot{token}/getMe',timeout=15); r.raise_for_status(); data=r.json()
    if not data.get('ok'): raise ValueError('توکن ربات معتبر نیست.')
    return data['result']

def assert_not_store_token(token,me=None):
    """Rule #7/#8: Store Token must never be reused as a Customer Bot token."""
    if token.strip()==BOT_TOKEN.strip(): raise ValueError('این توکن، توکن خودِ Eleven Store است و نمی‌تواند برای ربات مشتری استفاده شود.')
    if me and STORE_BOT_ID and me.get('id')==STORE_BOT_ID: raise ValueError('این توکن متعلق به ربات Eleven Store است و نمی‌تواند برای Instance مشتری استفاده شود.')

async def start_instance(bot_id):
    c=get_connection(); b=c.execute('SELECT * FROM bots WHERE id=?',(bot_id,)).fetchone(); c.close()
    if not b: raise ValueError('ربات پیدا نشد.')
    b=dict(b); b['bot_token']=reveal_token(b.get('bot_token',''))
    old=PROCESSES.get(bot_id)
    if old and old.returncode is None: return old.pid
    instance=Path(b['instance_path']); main=instance/'main.py'
    if not main.exists(): raise FileNotFoundError('سورس ربات مشتری داخل Instance وجود ندارد.')
    log_file=open(instance/'runtime.log','ab')
    proc=await asyncio.create_subprocess_exec(sys.executable,str(main),cwd=str(instance),env=instance_env(reveal_token(b['bot_token']),b['admin_id']),stdout=log_file,stderr=log_file)
    PROCESSES[bot_id]=proc
    c=get_connection(); c.execute("UPDATE bots SET process_pid=?,status='starting',last_error=NULL WHERE id=?",(proc.pid,bot_id)); c.commit(); c.close()
    await asyncio.sleep(3)
    if proc.returncode is not None:
        c=get_connection(); c.execute("UPDATE bots SET status='error',last_error=? WHERE id=?",(f'پردازش با کد {proc.returncode} متوقف شد.',bot_id)); c.commit(); c.close(); raise RuntimeError('ربات مشتری بعد از اجرا متوقف شد؛ runtime.log را بررسی کنید.')
    c=get_connection(); c.execute("UPDATE bots SET status='active' WHERE id=?",(bot_id,)); c.commit(); c.close(); return proc.pid

async def stop_instance(bot_id):
    proc=PROCESSES.get(bot_id)
    if proc and proc.returncode is None:
        proc.terminate()
        try: await asyncio.wait_for(proc.wait(),8)
        except asyncio.TimeoutError: proc.kill(); await proc.wait()
    c=get_connection(); c.execute("UPDATE bots SET status='stopped',process_pid=NULL WHERE id=?",(bot_id,)); c.commit(); c.close(); PROCESSES.pop(bot_id,None)

async def backup_bot(bot_id,kind='manual'):
    """Create a safe configuration snapshot, never executable source or raw SQL."""
    c=get_connection(); b=c.execute('SELECT * FROM bots WHERE id=?',(bot_id,)).fetchone(); c.close()
    if not b: raise ValueError('ربات پیدا نشد.')
    db=Path(b['instance_path'])/'database'/'app.db'
    if not db.exists(): raise FileNotFoundError('دیتابیس ربات مشتری پیدا نشد.')
    outdir=BASE/'backups'/f'bot-{bot_id}'; outdir.mkdir(parents=True,exist_ok=True)
    out=outdir/f'{kind}-{now().strftime("%Y%m%d-%H%M%S")}.json'
    snapshot={'format':'eleven-store-config-backup','version':2,'created_at':now().isoformat(),'bot':{'license_key':b['license_key'],'bot_username':b['bot_username'],'plan_name':b['plan_name'],'plan_key':b['plan_key'],'price':b['price'],'expires_at':b['expires_at']},'tables':{}}
    src=sqlite3.connect(db); src.row_factory=sqlite3.Row
    allowed={'settings':['key','value'],'products':['id','name','kind','data_gb','days','max_users','price','description','capacity','sold','enabled'],'custom_settings':['id','enabled','min_gb','max_gb','price_per_gb','min_days','max_days','price_per_month','price_limited_unlimited','price_per_day','ask_duration','default_days','users_enabled','min_users','max_users','price_per_user'],'payment_methods':['id','name','kind','card_number','card_holder','enabled','auto_approve','auto_approve_minutes']}
    for table,cols in allowed.items():
        try:
            rows=src.execute('SELECT '+','.join(cols)+' FROM '+table).fetchall()
            snapshot['tables'][table]=[dict(r) for r in rows]
        except sqlite3.Error:
            snapshot['tables'][table]=[]
    src.close(); out.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    c=get_connection(); c.execute('INSERT INTO bot_backups(bot_id,user_id,path,kind) VALUES(?,?,?,?)',(bot_id,b['user_id'],str(out),kind)); c.execute('UPDATE bots SET last_backup_at=? WHERE id=?',(now().isoformat(),bot_id)); c.commit(); c.close()
    return out

async def send_backup(context,chat_id,bot_id,kind='manual'):
    path=await backup_bot(bot_id,kind)
    with open(path,'rb') as f: await context.bot.send_document(chat_id,f,filename=path.name,caption='💾 بکاپ تنظیمات امن ربات — شامل تنظیمات و قیمت‌هاست و شامل سورس کد یا فایل اجرایی نیست.')

# ---------- user flow ----------
async def start(u,c):
    x=u.effective_user; existed=get_user_by_tid(x.id); upsert_user(x.id,x.username,x.first_name); ensure_products(); c.user_data.clear()
    if not existed: audit('user_joined',x.id,f'telegram_id={x.id} username=@{x.username or '-'}')
    payload=(u.message.text or '').split(maxsplit=1)[1] if u.message and (u.message.text or '').startswith('/start ') else ''
    if payload.startswith('ref_'):
        try:
            ref_tid=int(payload[4:]); ref=get_user_by_tid(ref_tid)
            if ref and ref['telegram_id']!=x.id: c.user_data['referrer_id']=ref['id']
        except Exception: pass
    pending=None
    try:
        db=get_connection(); pending=db.execute("SELECT id,plan_name FROM orders WHERE user_id=? AND status IN ('paid','provisioning') ORDER BY id DESC LIMIT 1",(user_row(x.id)['id'],)).fetchone(); db.close()
    except Exception: pass
    text=f'👋 خوش اومدی به {APP_NAME}\n\nاینجا لایسنس ربات فروش پنل می‌فروشه و برای هر خرید، یک Instance مستقل از رباتت راه‌اندازی می‌کنه.'
    if pending:
        text+='\n\n⏳ یک سفارش پرداخت‌شده داری که هنوز ساخت آن کامل نشده است.'
        await u.message.reply_text(text,reply_markup=kb([[btn('🤖 ادامه ساخت',f'continue_order:{pending["id"]}','success')],[btn('🏠 منوی اصلی','home')]]))
    else:
        await u.message.reply_text(text,reply_markup=home(x.id))

async def show_plans(q):
    ps=active_plans()
    if not ps: await q.edit_message_text('📭 فعلاً هیچ پلنی برای فروش تعریف نشده است.',reply_markup=kb([[btn('↩️ بازگشت','home')]])); return
    rows=[[btn(f'📦 {p["name"]} — {money(p["price"])}',f'plan:p{p["id"]}','primary')] for p in ps]
    rows.append([btn('↩️ بازگشت','home')]); await q.edit_message_text('📦 انتخاب لایسنس\n\nیکی از پلن‌ها را انتخاب کن:',reply_markup=kb(rows))

async def plan_selected(q,c,key):
    plan=get_plan(key)
    if not plan: await q.edit_message_text('❌ این پلن دیگر موجود نیست.',reply_markup=kb([[btn('↩️ بازگشت','build')]])); return
    name,price,days=plan; c.user_data.update({'plan':key,'price':price,'plan_name':name,'days':days,'state':'pay'}); u=user_row(q.from_user.id)
    card=get_method(); bal=u['balance']; shortage=max(0,price-bal)
    text=f'📦 {name}\n💰 قیمت: {money(price)}\n💳 موجودی کیف پول: {money(bal)}\n'
    if shortage: text+=f'\n📌 مبلغ قابل پرداخت: {money(shortage)}\n'
    else: text+='\n🟢 کل مبلغ از کیف پول پرداخت می‌شود.\n'
    rows=[]
    if shortage and card: rows.append([btn('💳 پرداخت کسری و ارسال رسید','pay_shortage','success')])
    if not shortage: rows.append([btn('🟢 پرداخت از کیف پول','pay_wallet','success')])
    rows.append([btn('💰 شارژ کیف پول','wallet')]); rows.append([btn('↩️ بازگشت','build')]); await q.edit_message_text(text,reply_markup=kb(rows))

async def ask_admin_id(q,c):
    c.user_data['state']='admin_id'; await q.edit_message_text('🆔 Admin ID ربات را ارسال کن.\n\nیا از دکمه زیر برای همین اکانت استفاده کن:',reply_markup=kb([[btn('🟢 همین اکانت ادمین باشه','my_admin_id','success')],[btn('🔵 اکانت دیگری می‌خواهم','other_admin_id','primary')],[btn('↩️ بازگشت','build')]]))

async def ask_token(q,c):
    c.user_data['state']='bot_token'; await q.edit_message_text('🔑 Bot Token ربات را ارسال کن.\n\nتوکن را از @BotFather بگیر.\nمثال ساختگی: `123456789:AAExampleToken`',parse_mode='Markdown',reply_markup=kb([[btn('↩️ بازگشت','build')]]))

async def review(q,c):
    d=c.user_data; text=f'🔍 بررسی اطلاعات\n\n📦 {d["plan_name"]}\n💰 {money(d["price"])}\n🆔 Admin ID: {d["admin_id"]}\n🔑 Token: ثبت شد\n\nاگر اطلاعات درست است، ساخت را شروع کن.'
    await q.edit_message_text(text,reply_markup=kb([[btn('🟢 ساخت و راه‌اندازی','provision','success')],[btn('↩️ بازگشت','build')]]))

async def provision(q,c):
    d=c.user_data; uid=user_row(q.from_user.id)
    if not all(k in d for k in ('plan','price','admin_id','bot_token')): await q.edit_message_text('❌ اطلاعات ناقص است.',reply_markup=home(q.from_user.id)); return
    try:
        me=await asyncio.to_thread(validate_token,d['bot_token'])
        assert_not_store_token(d['bot_token'],me)
    except Exception as e: await q.edit_message_text('❌ توکن معتبر نیست یا Telegram پاسخ نداد.\n'+str(e)[:400],reply_markup=kb([[btn('🔑 ورود دوباره توکن','ask_token')]])); return
    license_key='ELS-'+uuid.uuid4().hex[:12].upper(); instance=INSTANCES/f'bot-{uid["id"]}-{uuid.uuid4().hex[:8]}'; shutil.copytree(TEMPLATE,instance,dirs_exist_ok=True)
    (instance/'.env').write_text(f'BOT_TOKEN={d["bot_token"]}\nOWNER_ID={d["admin_id"]}\nAPP_NAME=PasarGuard Dealer\nLOG_LEVEL=INFO\n',encoding='utf-8')
    exp=(now()+timedelta(days=d['days'])).isoformat()
    db=get_connection(); cur=db.execute('INSERT INTO bots(user_id,license_key,telegram_bot_id,bot_username,bot_token,admin_id,plan_key,plan_name,price,status,instance_path,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uid['id'],license_key,me['id'],'@'+me['username'],protect_token(d['bot_token']),d['admin_id'],d['plan'],d['plan_name'],d['price'],'provisioning',str(instance),exp)); bot_id=cur.lastrowid
    if d.get('order_id'): db.execute("UPDATE orders SET status='provisioning',plan_key=?,plan_name=?,admin_id=?,bot_token=? WHERE id=?",(d['plan'],d['plan_name'],d['admin_id'],protect_token(d['bot_token']),d['order_id']))
    db.commit(); db.close()
    try:
        await start_instance(bot_id)
        if d.get('order_id'):
            db=get_connection(); db.execute("UPDATE orders SET status='completed',approved_at=? WHERE id=?",(now().isoformat(),d['order_id'])); db.commit(); db.close()
        audit('license_provisioned',uid['id'],f'bot={bot_id} order={d.get("order_id")} license={license_key}')
        c.user_data.clear(); await q.edit_message_text('🎉 ربات شما با موفقیت ساخته و راه‌اندازی شد!\n\n'+license_text(dict(get_bot(bot_id))),reply_markup=kb([[btn('⚙️ مدیریت ربات','bots','primary')],[btn('🏠 منوی اصلی','home')]]))
    except Exception as e:
        if d.get('order_id'): refund_wallet_once(uid['id'],int(d.get('price') or 0),int(d['order_id']),'بازگشت وجه به علت شکست ساخت Instance')
        db=get_connection(); db.execute("UPDATE bots SET status='error',last_error=? WHERE id=?",(str(e)[:1000],bot_id));
        if d.get('order_id'): db.execute("UPDATE orders SET status='error',error=? WHERE id=?",(str(e)[:1000],d['order_id']))
        db.commit(); db.close()
        await q.edit_message_text('❌ ساخت Instance با خطا مواجه شد. مبلغ رزرو شده در صورت پرداخت از کیف پول برگشت داده شد.\n\n'+str(e)[:600],reply_markup=kb([[btn('📄 مدیریت ربات','bots')],[btn('🏠 خانه','home')]]))

def get_bot(bot_id):
    c=get_connection(); r=c.execute('SELECT * FROM bots WHERE id=?',(bot_id,)).fetchone(); c.close()
    if not r: return None
    x=dict(r); x['bot_token']=reveal_token(x.get('bot_token','')); return x

def get_user_bots(uid):
    c=get_connection(); r=[dict(x) for x in c.execute('SELECT * FROM bots WHERE user_id=? ORDER BY id DESC',(uid,))]; c.close(); return r

# ---------- wallet / receipts ----------
async def wallet(q,c):
    u=user_row(q.from_user.id); await q.edit_message_text(f'💰 کیف پول\n\nموجودی: {money(u["balance"])}',reply_markup=kb([[btn('➕ شارژ کیف پول','topup')],[btn('↩️ بازگشت','home')]]))

async def topup(q,c): c.user_data['state']='topup_amount'; await q.edit_message_text('💳 مبلغ شارژ را به تومان ارسال کن.\nمثال: 20000',reply_markup=kb([[btn('↩️ بازگشت','wallet')]]))

async def receipt(u,c):
    if c.user_data.get('state')!='awaiting_receipt': return
    doc=u.message.document or u.message.photo[-1] if u.message.photo else None
    file_id=(u.message.document.file_id if u.message.document else u.message.photo[-1].file_id if u.message.photo else None)
    if not file_id: await u.message.reply_text('❌ فقط عکس یا فایل رسید ارسال کن.'); return
    oid=c.user_data.get('order_id'); amount=c.user_data.get('shortage',0)
    db=get_connection(); db.execute('UPDATE orders SET status="pending_review",receipt_at=?,receipt_file_id=? WHERE id=?',(now().isoformat(),file_id,oid)); db.commit(); db.close()
    card=get_method(); text=f'💳 رسید پرداخت جدید\n\n🧾 سفارش #{oid}\n👤 کاربر: {u.effective_user.id}\n💰 مبلغ: {money(amount)}\n💳 کارت مقصد: {card["card_number"] if card else "-"}'
    buttons=kb([[btn('🟢 تأیید پرداخت',f'approve:{oid}','success'),btn('🔴 رد پرداخت',f'reject:{oid}','danger')]])
    if u.message.photo:
        await c.bot.send_photo(OWNER_ID, file_id, caption=text, reply_markup=buttons)
    elif u.message.document:
        await c.bot.send_document(OWNER_ID, file_id, caption=text, reply_markup=buttons)
    else:
        await c.bot.send_message(OWNER_ID,text,reply_markup=buttons)
    await u.message.reply_text('✅ رسید ارسال شد. بعد از تأیید ادمین، ربات ساخته می‌شود.',reply_markup=home(u.effective_user.id)); c.user_data.clear()

# ---------- free trial ----------
async def trial_start(q,c):
    usr=user_row(q.from_user.id)
    db=get_connection(); claimed=db.execute("SELECT 1 FROM trial_usages WHERE user_id=? LIMIT 1",(usr["id"],)).fetchone(); db.close()
    if claimed:
        await q.edit_message_text("ℹ️ شما قبلاً از تست رایگان استفاده کرده‌اید.",reply_markup=kb([[btn("↩️ بازگشت","home")]])); return
    c.user_data.clear(); c.user_data["trial_mode"]=True; c.user_data["trial_minutes"]=120; c.user_data["trial_volume_gb"]=5
    await q.edit_message_text("🎁 دریافت تست رایگان ۲ ساعته\n\nبرای شروع، مدیر ربات را مشخص کنید.",reply_markup=kb([[btn("👤 همین حساب، مدیر ربات باشد","my_admin_id","success")],[btn("👥 یک حساب دیگر در نظر دارم","other_admin_id","primary")],[btn("↩️ بازگشت","home")]]))

async def provision_trial(q,c):
    d=c.user_data; uid=user_row(q.from_user.id)
    if not d.get("trial_mode") or not d.get("admin_id") or not d.get("bot_token"):
        await q.edit_message_text("❌ اطلاعات تست کامل نیست.",reply_markup=kb([[btn("↩️ بازگشت","home")]])); return
    db=get_connection(); claimed=db.execute("SELECT 1 FROM trial_usages WHERE user_id=? LIMIT 1",(uid["id"],)).fetchone(); db.close()
    if claimed:
        c.user_data.clear(); await q.edit_message_text("ℹ️ شما قبلاً از تست رایگان استفاده کرده‌اید.",reply_markup=kb([[btn("↩️ بازگشت","home")]])); return
    try:
        me=await asyncio.to_thread(validate_token,d["bot_token"]); assert_not_store_token(d["bot_token"],me)
        license_key='ELT-'+uuid.uuid4().hex[:12].upper(); instance=INSTANCES/f'trial-{uid["id"]}-{uuid.uuid4().hex[:8]}'; shutil.copytree(TEMPLATE,instance,dirs_exist_ok=True)
        (instance/'.env').write_text(f'BOT_TOKEN={d["bot_token"]}\nOWNER_ID={d["admin_id"]}\nAPP_NAME=PasarGuard Dealer\nLOG_LEVEL=INFO\n',encoding='utf8')
        exp=(now()+timedelta(minutes=120)).isoformat()
        db=get_connection(); cur=db.execute('INSERT INTO bots(user_id,license_key,telegram_bot_id,bot_username,bot_token,admin_id,plan_key,plan_name,price,status,instance_path,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uid['id'],license_key,me['id'],'@'+me['username'],protect_token(d['bot_token']),d['admin_id'],'trial','تست رایگان ۲ ساعته',0,'provisioning',str(instance),exp)); bid=cur.lastrowid; db.commit(); db.close()
        try:
            await start_instance(bid)
        except Exception:
            shutil.rmtree(instance,ignore_errors=True); db=get_connection(); db.execute("UPDATE bots SET status='error',last_error=? WHERE id=?",('ساخت تست رایگان ناموفق بود.',bid)); db.commit(); db.close(); raise
        db=get_connection(); db.execute('INSERT INTO trial_usages(user_id,bot_id) VALUES(?,?)',(uid['id'],bid)); db.commit(); db.close()
        c.user_data.clear(); await q.edit_message_text('🎉 تست رایگان شما با موفقیت راه‌اندازی شد.\n\n⏱ مدت اعتبار: ۲ ساعت\n🛑 پس از پایان ۲ ساعت، تست متوقف، بکاپ ارسال و Instance به‌طور کامل حذف می‌شود.',reply_markup=kb([[btn('📦 اشتراک‌های من','bots')],[btn('↩️ بازگشت','home')]]))
    except Exception as e:
        log.exception('trial provisioning failed'); await q.edit_message_text('❌ ساخت تست رایگان ناموفق بود.\n\n'+str(e)[:500],reply_markup=kb([[btn('↩️ بازگشت','home')]]))

# ---------- management ----------
async def bots_menu(q,c):
    bs=get_user_bots(user_row(q.from_user.id)['id']); rows=[[btn('🤖 ساخت ربات','build','success')]]
    for b in bs: rows.append([btn(f'🤖 {b["bot_username"] or "ربات"} | {b["plan_name"]}',f'bot:{b["id"]}')])
    rows.append([btn('↩️ بازگشت','home')]); await q.edit_message_text('⚙️ مدیریت ربات\n\nربات موردنظر را انتخاب کن:',reply_markup=kb(rows))

async def bot_manage(q,bot_id):
    b=get_bot(bot_id)
    if not b or b['user_id']!=user_row(q.from_user.id)['id']: return
    rows=[[btn('👤 تغییر ادمین',f'change_admin:{bot_id}')],[btn('🔑 تغییر توکن',f'change_token:{bot_id}')],[btn('💾 دریافت بکاپ',f'backup:{bot_id}')],[btn('📥 وارد کردن بکاپ',f'import_backup:{bot_id}')],[btn('🔀 انتقال ربات',f'transfer:{bot_id}')],[btn('📦 تغییر لایسنس',f'change_plan:{bot_id}')],[btn('📅 تمدید ربات',f'renew:{bot_id}')],[btn('🗑 حذف ربات',f'delete:{bot_id}','danger')],[btn('↩️ ربات‌ها','bots')]]
    await q.edit_message_text(license_text(b),reply_markup=kb(rows))

# ---------- admin ----------
async def admin_panel(q):
    await q.edit_message_text('👑 پنل ادمین\n\nمدیریت کامل Eleven Store:',reply_markup=kb([
      [btn('👥 کاربران','a_users'),btn('🤖 ربات‌ها','a_bots')],[btn('📦 لایسنس‌ها','a_licenses'),btn('💳 پرداخت‌ها','a_payments')],[btn('💰 کیف پول‌ها','a_wallets'),btn('🎁 زیرمجموعه‌ها','a_referrals')],[btn('💾 بکاپ‌ها','a_backups'),btn('🆘 پشتیبانی','a_support')],[btn('🛒 محصولات','a_products'),btn('✏️ مدیریت متن‌ها','a_texts')],[btn('💳 کارت‌های بانکی','a_cards'),btn('📊 گزارش‌ها','a_reports')],[btn('⚙️ تنظیمات','a_settings')],[btn('↩️ بازگشت','home')]]))

async def admin_users(q,query=None):
    us=list_users('all',query); rows=[[btn(f'👤 {x.get("username") or x.get("first_name") or x["telegram_id"]} | {money(x.get("balance",0))}',f'auser:{x["id"]}')] for x in us[:50]]
    rows.insert(0,[btn('🔎 جستجو با آیدی عددی','a_users_search','primary')])
    rows.append([btn('↩️ ادمین','admin')])
    body=SECTION_HELP['a_users']+(f'\n\n🔎 نتیجه جستجو برای «{query}»:' if query else '\n\nآخرین کاربران:')
    await q.edit_message_text(body,reply_markup=kb(rows))

def user_detail_text(x):
    db=get_connection()
    orders_c=db.execute('SELECT COUNT(*) c FROM orders WHERE user_id=?',(x['id'],)).fetchone()['c']
    bots=db.execute('SELECT id,bot_username,plan_name,status,expires_at FROM bots WHERE user_id=? ORDER BY id DESC',(x['id'],)).fetchall()
    tx_c=db.execute('SELECT COUNT(*) c FROM transactions WHERE user_id=?',(x['id'],)).fetchone()['c']
    db.close()
    lic='\n'.join(f'  • #{b["id"]} @{b["bot_username"] or "-"} | {b["plan_name"]} | {b["status"]} | تا {b["expires_at"] or "-"}' for b in bots) or '  —'
    blocked='🔴 مسدود' if is_blocked(x['id']) else '🟢 آزاد'
    return (f'👤 کاربر #{x["id"]}\n'
            f'🆔 Telegram ID: <code>{x["telegram_id"]}</code>\n'
            f'📛 Username: @{x.get("username") or "-"}\n'
            f'👋 نام: {x.get("first_name") or "-"}\n'
            f'📅 عضویت: {x.get("created_at") or "-"}\n'
            f'💰 موجودی کیف پول: {money(x.get("balance",0))}\n'
            f'🧾 تعداد سفارش‌ها: {orders_c}\n'
            f'💳 تعداد تراکنش‌ها: {tx_c}\n'
            f'وضعیت: {blocked}\n\n'
            f'🤖 ربات‌ها/لایسنس‌ها:\n{lic}')

async def admin_user_detail(q,target_id):
    x=get_user(target_id)
    if not x: await q.edit_message_text('❌ کاربر پیدا نشد.',reply_markup=kb([[btn('↩️ کاربران','a_users')]])); return
    blocked=is_blocked(x['id'])
    rows=[[btn('➕ افزایش موجودی',f'ubal_add:{x["id"]}','success'),btn('➖ کاهش موجودی',f'ubal_sub:{x["id"]}','danger')],
          [btn('🔓 رفع مسدودی' if blocked else '🔒 مسدود کردن',f'uunblock:{x["id"]}' if blocked else f'ublock:{x["id"]}','danger' if not blocked else 'success')],
          [btn('↩️ کاربران','a_users')]]
    await q.edit_message_text(user_detail_text(x),parse_mode='HTML',reply_markup=kb(rows))

# ---------- admin submenus ----------
async def simple_admin(q,title,body,back='admin'):
    await q.edit_message_text(title+'\n\n'+body,reply_markup=kb([[btn('↩️ بازگشت',back)]]))

async def admin_bots(q):
    db=get_connection(); rows=db.execute('SELECT id,user_id,bot_username,plan_name,status,expires_at FROM bots ORDER BY id DESC LIMIT 50').fetchall(); db.close()
    body='\n'.join(f'#{r["id"]} | {r["bot_username"] or "-"} | {r["status"]} | {r["plan_name"]}' for r in rows) or '📭 رباتی ثبت نشده است.'
    await simple_admin(q,'🤖 ربات‌ها',SECTION_HELP['a_bots']+'\n\n'+body)
async def admin_licenses(q):
    db=get_connection(); rows=db.execute('SELECT plan_name,COUNT(*) c FROM bots GROUP BY plan_name').fetchall(); db.close()
    body='\n'.join(f'📦 {r["plan_name"]}: {r["c"]}' for r in rows) or '📭 لایسنسی ثبت نشده است.'
    await simple_admin(q,'📦 لایسنس‌ها',SECTION_HELP['a_licenses']+'\n\n'+body)
async def admin_payments(q):
    db=get_connection(); rows=db.execute('SELECT id,user_id,total_amount,status,created_at FROM orders ORDER BY id DESC LIMIT 50').fetchall(); db.close()
    body='\n'.join(f'#{r["id"]} | {money(r["total_amount"])} | {r["status"]}' for r in rows) or '📭 پرداختی نیست.'
    await simple_admin(q,'💳 پرداخت‌ها',SECTION_HELP['a_payments']+'\n\n'+body)
async def admin_wallets(q):
    db=get_connection(); r=db.execute('SELECT COUNT(*) users,COALESCE(SUM(balance),0) total FROM users').fetchone(); db.close(); await simple_admin(q,'💰 کیف پول‌ها',SECTION_HELP['a_wallets']+f'\n\n👥 کاربران: {r["users"]}\n💰 مجموع موجودی: {money(r["total"])}')
async def admin_referrals(q): await simple_admin(q,'🎁 زیرمجموعه‌ها',SECTION_HELP['a_referrals']+'\n\nاین بخش آماده توسعه است؛ داده‌ای از سیستم قبلی وارد نمی‌شود.')
async def admin_backups(q):
    db=get_connection(); rows=db.execute('SELECT bot_id,kind,created_at,path FROM bot_backups ORDER BY id DESC LIMIT 30').fetchall(); db.close(); body='\n'.join(f'🤖 #{r["bot_id"]} | {r["kind"]} | {r["created_at"]}' for r in rows) or '📭 بکاپی ثبت نشده است.'; await simple_admin(q,'💾 بکاپ‌ها',SECTION_HELP['a_backups']+'\n\n'+body)
async def admin_support(q):
    tickets=list_open_tickets()
    rows=[[btn(f'🆘 تیکت #{t["id"]} | کاربر {get_user(t["user_id"])["telegram_id"] if get_user(t["user_id"]) else "-"}',f'ticket:{t["id"]}')] for t in tickets]
    rows.append([btn('↩️ بازگشت','admin')])
    body=SECTION_HELP['a_support']+('\n\n📭 تیکت باز وجود ندارد.' if not tickets else f'\n\n{len(tickets)} تیکت باز:')
    await q.edit_message_text(body,reply_markup=kb(rows))
async def admin_products(q):
    ps=list_products(False)
    rows=[[btn('➕ افزودن محصول','padd','success')]]
    for p in ps:
        state='🟢' if p['enabled'] else '🔴'
        rows.append([btn(f'{state} {p["name"]} | {money(p["price"])} | {p["days"]} روز',f'pedit:{p["id"]}')])
    rows.append([btn('↩️ بازگشت','admin')])
    body=SECTION_HELP['a_products']+('\n\n📭 هنوز محصولی ثبت نشده.' if not ps else '\n\nبرای ویرایش یا حذف، روی محصول بزن.')
    await q.edit_message_text(body,reply_markup=kb(rows))

async def admin_texts(q):
    keys=[('welcome_text','👋 متن خوش‌آمدگویی'),('support_text','🆘 متن راهنمای پشتیبانی'),('bot_name','🏷 نام نمایشی ربات'),('support_username','👤 آیدی پشتیبانی'),('support_link','🔗 لینک پشتیبانی')]
    rows=[[btn(f'✏️ {label}',f'tedit:{key}')] for key,label in keys]
    rows.append([btn('↩️ بازگشت','admin')])
    preview='\n'.join(f'• {label}: {setting(key) or "—"}' for key,label in keys)
    await q.edit_message_text(SECTION_HELP['a_texts']+'\n\n'+preview,reply_markup=kb(rows))
async def admin_reports(q):
    db=get_connection(); r=db.execute('SELECT COUNT(*) bots FROM bots;').fetchone(); o=db.execute('SELECT COUNT(*) orders FROM orders').fetchone(); db.close(); await simple_admin(q,'📊 گزارش‌ها',SECTION_HELP['a_reports']+f'\n\n🤖 ربات‌ها: {r["bots"]}\n🧾 سفارش‌ها: {o["orders"]}')
async def admin_settings(q): await simple_admin(q,'⚙️ تنظیمات',SECTION_HELP['a_settings']+'\n\n💾 بکاپ SQL دوره‌ای: فعال\n⏰ بررسی و بکاپ خودکار انقضا: فعال')

# ---------- callback router ----------
async def callback(u,c):
    q=u.callback_query; await q.answer(); d=q.data; uid=q.from_user.id
    if d=='noop': return
    if d=='home': await q.edit_message_text('🏠 منوی اصلی',reply_markup=home(uid)); return
    if d=='build': await show_plans(q); return
    if d=='trial_start': await trial_start(q,c); return
    if d=='trial_provision': await provision_trial(q,c); return
    if d.startswith('plan:'): await plan_selected(q,c,d.split(':',1)[1]); return
    if d=='pay_wallet':
        x=c.user_data; usr=user_row(uid); price=int(x['price'])
        db=get_connection(); cur=db.execute('INSERT INTO orders(user_id,total_amount,wallet_amount,card_amount,status,kind,plan_key,plan_name) VALUES(?,?,?,?,?,?,?,?)',(usr['id'],price,price,0,'awaiting_payment','license',x['plan'],x['plan_name'])); oid=cur.lastrowid; db.commit(); db.close()
        if not atomic_wallet_hold(usr['id'],price,oid):
            db=get_connection(); db.execute("DELETE FROM orders WHERE id=? AND status='awaiting_payment'",(oid,)); db.commit(); db.close(); await q.edit_message_text('❌ موجودی کافی نیست یا همزمان تغییر کرده است.',reply_markup=kb([[btn('💰 کیف پول','wallet')]])); return
        db=get_connection(); db.execute("UPDATE orders SET status='paid' WHERE id=?",(oid,)); db.commit(); db.close()
        x['order_id']=oid; c.user_data['paid']=True; await ask_admin_id(q,c); return
    if d=='pay_shortage':
        x=c.user_data; usr=user_row(uid); card=get_method(); shortage=max(0,x['price']-usr['balance'])
        if not card: await q.edit_message_text('❌ کارت پرداخت تنظیم نشده است.',reply_markup=kb([[btn('↩️ بازگشت','build')]])); return
        db=get_connection(); cur=db.execute('INSERT INTO orders(user_id,total_amount,wallet_amount,card_amount,status,kind,plan_key,plan_name) VALUES(?,?,?,?,?,?,?,?)',(usr['id'],x['price'],usr['balance'],shortage,'awaiting_receipt','license',x['plan'],x['plan_name'])); oid=cur.lastrowid; db.commit(); db.close()
        x['order_id']=oid; x['shortage']=shortage; x['state']='awaiting_receipt'; await q.edit_message_text(f'💳 پرداخت کسری\n\n💰 قیمت: {money(x["price"])}\n💳 کیف پول: {money(usr["balance"])}\n📌 مبلغ قابل پرداخت: {money(shortage)}\n\n💳 کارت پرداخت:\n<code>{card["card_number"]}</code>\n👤 صاحب کارت: {card["card_holder"]}\n\nبعد از پرداخت، رسید را همینجا ارسال کن.',parse_mode='HTML',reply_markup=kb([[btn('↩️ لغو','build')]])); return
    if d=='my_admin_id': c.user_data['admin_id']=uid; await ask_token(q,c); return
    if d=='ask_token': await ask_token(q,c); return
    if d.startswith('continue_order:'):
        oid=int(d.split(':',1)[1]); db=get_connection(); o=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); db.close()
        if not o or o['user_id']!=user_row(uid)['id'] or o['status']!='paid': return
        _plan=get_plan(o['plan_key']); _days=_plan[2] if _plan else 0
        c.user_data.clear(); c.user_data.update({'order_id':oid,'plan':o['plan_key'],'plan_name':o['plan_name'],'price':o['total_amount'],'days':_days,'state':'admin_id'})
        await ask_admin_id(q,c); return
    if d=='provision': await provision(q,c); return
    if d=='referral':
        me=user_row(uid); name=setting('bot_username','ElevenStoreBot').lstrip('@')
        await q.edit_message_text(f'👥 زیرمجموعه‌گیری\n\nکد دعوت شما: <code>ELS{me["telegram_id"]}</code>\n\nلینک دعوت:\nt.me/{name}?start=ref_{me["telegram_id"]}',parse_mode='HTML',reply_markup=kb([[btn('↩️ بازگشت','home')]])); return
    if d=='topup_paid':
        if c.user_data.get('state')!='topup_waiting_payment': return
        c.user_data['state']='topup_receipt'; await q.edit_message_text('📸 حالا تصویر یا فایل رسید پرداخت را ارسال کن.\n\nفقط رسید همین تراکنش را بفرست.',reply_markup=kb([[btn('↩️ لغو','wallet')]])); return
    if d=='other_admin_id':
        c.user_data['state']='admin_id'; await q.edit_message_text('🆔 آیدی عددی اکانت ادمین دیگر را ارسال کن.\n\nمثال: `123456789`',parse_mode='Markdown',reply_markup=kb([[btn('↩️ بازگشت','build')]])); return
    if d=='support':
        c.user_data.clear(); usr=user_row(uid); t=get_open_ticket(usr['id'])
        if t:
            c.user_data['state']='support_msg'
            await q.edit_message_text('📝 یک تیکت باز داری. پیام جدیدت برای همان تیکت ارسال می‌شود؛ لطفاً متن پیام خود را ارسال کنید.',reply_markup=kb([[btn('↩️ بازگشت','home')]]))
        else:
            c.user_data['state']='support_msg'
            await q.edit_message_text('📝 لطفاً متن پیام خود را ارسال کنید.',reply_markup=kb([[btn('↩️ بازگشت','home')]]))
        return
    if d=='wallet': await wallet(q,c); return
    if d=='topup': await topup(q,c); return
    if d=='bots': await bots_menu(q,c); return
    if d.startswith('bot:'): await bot_manage(q,int(d.split(':')[1])); return
    if d.startswith('backup:'):
        b=get_bot(int(d.split(':')[1]));
        if b and b['user_id']==user_row(uid)['id']: await send_backup(c,q.message.chat_id,b['id']); await q.message.reply_text('✅ بکاپ تنظیمات امن ارسال شد.');
        return
    if d.startswith('delete:'):
        bid=int(d.split(':')[1]); b=get_bot(bid)
        if not b or b['user_id']!=user_row(uid)['id']: return
        await q.edit_message_text('⚠️ قبل از حذف، یک بکاپ نهایی گرفته می‌شود.\n\nآیا مطمئنی؟',reply_markup=kb([[btn('🔴 تأیید حذف',f'confirm_delete:{bid}','danger')],[btn('↩️ لغو',f'bot:{bid}')]])); return
    if d.startswith('confirm_delete:'):
        bid=int(d.split(':')[1]); b=get_bot(bid)
        if b and b['user_id']==user_row(uid)['id']:
            try: await backup_bot(bid,'delete-final')
            except Exception as e:
                await q.edit_message_text('❌ بکاپ نهایی ساخته نشد؛ برای جلوگیری از حذف بدون بکاپ، ربات حذف نشد.\n\n'+str(e)[:500],reply_markup=kb([[btn('↩️ بازگشت',f'bot:{bid}')]])); return
            await stop_instance(bid); shutil.rmtree(b['instance_path'],ignore_errors=True); db=get_connection(); db.execute("UPDATE bots SET status='deleted',process_pid=NULL WHERE id=?",(bid,)); db.commit(); db.close(); await bots_menu(q,c)
        return
    if d=='admin' and admin(uid): await admin_panel(q); return
    if d=='a_users' and admin(uid): await admin_users(q); return
    if d=='a_users_search' and admin(uid): c.user_data.clear(); c.user_data['state']='user_search'; await q.edit_message_text('🔎 آیدی عددی تلگرام کاربر را ارسال کن.',reply_markup=kb([[btn('↩️ بازگشت','a_users')]])); return
    if d.startswith('auser:') and admin(uid): await admin_user_detail(q,int(d.split(':')[1])); return
    if d.startswith('ubal_add:') and admin(uid):
        c.user_data.clear(); c.user_data.update({'state':'ubal_amount','ubal_uid':int(d.split(':')[1]),'ubal_sign':1}); await q.edit_message_text('➕ مبلغ افزایش موجودی را به تومان ارسال کن.',reply_markup=kb([[btn('↩️ لغو',f'auser:{d.split(":")[1]}')]])); return
    if d.startswith('ubal_sub:') and admin(uid):
        c.user_data.clear(); c.user_data.update({'state':'ubal_amount','ubal_uid':int(d.split(':')[1]),'ubal_sign':-1}); await q.edit_message_text('➖ مبلغ کاهش موجودی را به تومان ارسال کن.',reply_markup=kb([[btn('↩️ لغو',f'auser:{d.split(":")[1]}')]])); return
    if d=='ubal_confirm' and admin(uid):
        tgt=c.user_data.get('ubal_uid'); amount=c.user_data.get('ubal_amount'); sign=c.user_data.get('ubal_sign',1)
        if tgt and amount:
            set_balance(tgt,sign*amount,'admin_adjustment',f'تغییر دستی توسط ادمین {uid}'); tu=get_user(tgt)
            if tu: 
                try: await c.bot.send_message(tu['telegram_id'],('🟢 موجودی کیف پول شما %s شد: %s'%('افزایش' if sign>0 else 'کاهش',money(amount))))
                except Exception: pass
        c.user_data.clear(); await admin_user_detail(q,tgt); return
    if d=='ubal_cancel' and admin(uid):
        tgt=c.user_data.get('ubal_uid'); c.user_data.clear()
        if tgt: await admin_user_detail(q,tgt)
        else: await admin_users(q)
        return
    if d.startswith('ublock:') and admin(uid):
        tgt=int(d.split(':')[1]); set_blocked(tgt,True); await admin_user_detail(q,tgt); return
    if d.startswith('uunblock:') and admin(uid):
        tgt=int(d.split(':')[1]); set_blocked(tgt,False); await admin_user_detail(q,tgt); return
    if d=='a_cards' and admin(uid):
        cards=list_methods(); text='💳 کارت‌های بانکی\n\n'+('\n'.join(f'#{x["id"]} | {x["card_number"]} | {x["card_holder"]}' for x in cards) or 'هنوز کارتی ثبت نشده است.'); await q.edit_message_text(text,reply_markup=kb([[btn('➕ افزودن کارت','add_card','success')],[btn('↩️ ادمین','admin')]])); return
    if d=='add_card' and admin(uid): c.user_data['state']='card_number'; await q.edit_message_text('💳 شماره کارت را ارسال کن.'); return
    if d=='a_bots' and admin(uid): await admin_bots(q); return
    if d=='a_licenses' and admin(uid): await admin_licenses(q); return
    if d=='a_payments' and admin(uid): await admin_payments(q); return
    if d=='a_wallets' and admin(uid): await admin_wallets(q); return
    if d=='a_referrals' and admin(uid): await admin_referrals(q); return
    if d=='a_backups' and admin(uid): await admin_backups(q); return
    if d=='a_support' and admin(uid): await admin_support(q); return
    if d=='a_products' and admin(uid): await admin_products(q); return
    if d=='padd' and admin(uid): c.user_data.clear(); c.user_data['state']='prod_name'; await q.edit_message_text('📦 نام محصول را ارسال کن.',reply_markup=kb([[btn('↩️ لغو','a_products')]])); return
    if d.startswith('pedit:') and admin(uid):
        pid=int(d.split(':')[1]); p=get_product(pid)
        if not p: await admin_products(q); return
        state='🟢 فعال' if p['enabled'] else '🔴 غیرفعال'
        text=f'📦 {p["name"]}\n💰 {money(p["price"])}\n📅 {p["days"]} روز\n📝 {p["description"] or "-"}\nوضعیت: {state}'
        rows=[[btn('✏️ نام',f'pedit_f:{pid}:name'),btn('✏️ قیمت',f'pedit_f:{pid}:price')],
              [btn('✏️ مدت (روز)',f'pedit_f:{pid}:days'),btn('✏️ توضیحات',f'pedit_f:{pid}:description')],
              [btn('🔴 غیرفعال کردن' if p['enabled'] else '🟢 فعال کردن',f'ptoggle:{pid}')],
              [btn('🗑 حذف محصول',f'pdel:{pid}','danger')],
              [btn('↩️ بازگشت','a_products')]]
        await q.edit_message_text(text,reply_markup=kb(rows)); return
    if d.startswith('pedit_f:') and admin(uid):
        _,pid_s,field=d.split(':'); c.user_data.clear(); c.user_data.update({'state':'edit_prod_field','edit_pid':int(pid_s),'edit_field':field})
        await q.edit_message_text('✏️ مقدار جدید را ارسال کن.',reply_markup=kb([[btn('↩️ لغو',f'pedit:{pid_s}')]])); return
    if d.startswith('ptoggle:') and admin(uid):
        pid=int(d.split(':')[1]); toggle_product(pid); await q.edit_message_text('✅ وضعیت محصول تغییر کرد.',reply_markup=kb([[btn('↩️ محصولات','a_products')]])); return
    if d.startswith('pdel:') and admin(uid):
        pid=int(d.split(':')[1]); await q.edit_message_text('⚠️ آیا از حذف این محصول مطمئنی؟ (تا وقتی لایسنس‌های فعلی وجود دارند، این کار روی رباتِ‌های ساخته‌شده تأثیری ندارد.)',reply_markup=kb([[btn('🔴 تأیید حذف',f'pdel_confirm:{pid}','danger')],[btn('↩️ لغو',f'pedit:{pid}')]])); return
    if d.startswith('pdel_confirm:') and admin(uid):
        pid=int(d.split(':')[1]); delete_product(pid); await q.edit_message_text('✅ محصول حذف شد.',reply_markup=kb([[btn('↩️ محصولات','a_products')]])); return
    if d=='a_texts' and admin(uid): await admin_texts(q); return
    if d.startswith('tedit:') and admin(uid):
        key=d.split(':',1)[1]; c.user_data.clear(); c.user_data.update({'state':'edit_text_key','edit_key':key})
        await q.edit_message_text(f'✏️ مقدار جدید برای «{key}» را ارسال کن.\n\nمقدار فعلی:\n{setting(key) or "—"}',reply_markup=kb([[btn('↩️ لغو','a_texts')]])); return
    if d.startswith('ticket:') and admin(uid):
        tid=int(d.split(':')[1]); t=get_ticket(tid)
        if not t: await admin_support(q); return
        msgs=list_messages(tid); body='\n\n'.join(('👤 کاربر: ' if m['sender']=='user' else '🔵 ادمین: ')+m['text'] for m in msgs[-15:])
        rows=[[btn('🔵 پاسخ',f'ticket_reply:{tid}')]]
        if t['status']=='open': rows.append([btn('🔒 بستن تیکت',f'ticket_close:{tid}','danger')])
        rows.append([btn('↩️ پشتیبانی','a_support')])
        await q.edit_message_text(f'🆘 تیکت #{tid} | وضعیت: {"باز" if t["status"]=="open" else "بسته"}\n\n{body}',reply_markup=kb(rows)); return
    if d.startswith('ticket_reply:') and admin(uid):
        tid=int(d.split(':')[1]); c.user_data.clear(); c.user_data.update({'state':'ticket_reply','ticket_id':tid})
        await q.edit_message_text('✏️ متن پاسخ را ارسال کن.',reply_markup=kb([[btn('↩️ لغو',f'ticket:{tid}')]])); return
    if d.startswith('ticket_close:') and admin(uid):
        tid=int(d.split(':')[1]); close_ticket(tid); t=get_ticket(tid)
        if t:
            tu=get_user(t['user_id'])
            if tu:
                try: await c.bot.send_message(tu['telegram_id'],'🔒 تیکت پشتیبانی شما بسته شد. در صورت نیاز دوباره پیام بده.')
                except Exception: pass
        await q.edit_message_text('✅ تیکت بسته شد.',reply_markup=kb([[btn('🆘 پشتیبانی','a_support')]])); return
    if d=='a_reports' and admin(uid): await admin_reports(q); return
    if d=='a_settings' and admin(uid): await admin_settings(q); return
    if d.startswith('topup_ok:') and admin(uid):
        tid=int(d.split(':')[1]); db=get_connection()
        try:
            db.execute('BEGIN IMMEDIATE'); r=db.execute('SELECT * FROM wallet_topups WHERE id=?',(tid,)).fetchone()
            if not r or r['status']!='pending_review': db.rollback(); db.close(); await q.answer('این درخواست قبلاً پردازش شده است.',show_alert=True); return
            db.execute("UPDATE wallet_topups SET status='completed',approved_by=?,approved_at=? WHERE id=? AND status='pending_review'",(uid,now().isoformat(),tid))
            if db.total_changes<1: db.rollback(); db.close(); await q.answer('این درخواست قبلاً پردازش شده است.',show_alert=True); return
            db.execute("UPDATE users SET balance=balance+? WHERE id=?",(r['amount'],r['user_id'])); db.execute("INSERT INTO transactions(user_id,amount,type,description) VALUES(?,?,?,?)",(r['user_id'],r['amount'],'wallet_topup','شارژ کیف پول'))
            db.commit()
        finally: db.close()
        await edit_callback_message(q, '🟢 شارژ کیف پول تأیید شد.'); u2=get_user(r['user_id']); audit('wallet_topup_approved',uid,f'topup={tid} amount={r["amount"]}'); await c.bot.send_message(u2['telegram_id'],f'🟢 کیف پول شما {money(r["amount"])} شارژ شد.'); return
    if d.startswith('topup_no:') and admin(uid):
        tid=int(d.split(':')[1]); db=get_connection(); r=db.execute('SELECT * FROM wallet_topups WHERE id=?',(tid,)).fetchone(); db.execute("UPDATE wallet_topups SET status='rejected',rejected_by=?,rejected_at=? WHERE id=? AND status='pending_review'",(uid,now().isoformat(),tid)); db.commit(); db.close(); await edit_callback_message(q, '🔴 درخواست شارژ رد شد.');
        if r: await c.bot.send_message(usr_tid(r['user_id']),'❌ درخواست شارژ کیف پول شما رد شد.')
        return
    if d.startswith('change_admin:'):
        bid=int(d.split(':')[1]); b=get_bot(bid)
        if b and b['user_id']==user_row(uid)['id']: c.user_data.clear(); c.user_data.update({'state':'change_admin','bot_id':bid}); await q.edit_message_text('🆔 Admin ID جدید را ارسال کن.');
        return
    if d.startswith('change_token:'):
        bid=int(d.split(':')[1]); b=get_bot(bid)
        if b and b['user_id']==user_row(uid)['id']: c.user_data.clear(); c.user_data.update({'state':'change_token','bot_id':bid}); await q.edit_message_text('🔑 Bot Token جدید را ارسال کن.');
        return
    if d.startswith('transfer:'):
        bid=int(d.split(':')[1]); b=get_bot(bid)
        if b and b['user_id']==user_row(uid)['id']: c.user_data.clear(); c.user_data.update({'state':'transfer','bot_id':bid}); await q.edit_message_text('🆔 Telegram ID مالک جدید را ارسال کن.');
        return
    if d.startswith('change_plan:'):
        bid=int(d.split(':')[1]); b=get_bot(bid)
        if b and b['user_id']==user_row(uid)['id']:
            ps=active_plans()
            if not ps: await q.edit_message_text('📭 فعلاً پلن دیگری برای تعویض تعریف نشده.',reply_markup=kb([[btn('↩️ بازگشت',f'bot:{bid}')]])); return
            await q.edit_message_text('📦 لایسنس جدید را انتخاب کن:',reply_markup=kb([[btn(f'{p["name"]} — {money(p["price"])}',f'apply_plan:{bid}:p{p["id"]}')] for p in ps]+[[btn('↩️ بازگشت',f'bot:{bid}')]]))
        return
    if d.startswith('apply_plan:'):
        _,bid_s,key=d.split(':'); bid=int(bid_s); b=get_bot(bid)
        if not b or b['user_id']!=user_row(uid)['id']: return
        plan=get_plan(key)
        if not plan: await q.edit_message_text('❌ این پلن دیگر موجود نیست.',reply_markup=kb([[btn('↩️ بازگشت',f'bot:{bid}')]])); return
        newname,newprice,newdays=plan; diff=newprice-int(b['price']); usr=user_row(uid)
        if diff>0 and usr['balance']<diff: await q.edit_message_text(f'❌ موجودی کافی نیست.\nمبلغ کمبود: {money(diff)}',reply_markup=kb([[btn('💰 کیف پول','wallet')],[btn('↩️ بازگشت',f'bot:{bid}')]])); return
        if diff: set_balance(usr['id'],-diff if diff>0 else -diff,'license_change',newname)
        oldplan=get_plan(b['plan_key']); olddays=oldplan[2] if oldplan else 0
        oldexp=datetime.fromisoformat(b['expires_at']) if b['expires_at'] else now(); remaining=max(0,(oldexp-now()).days); extra=max(0,newdays-olddays); exp=(now()+timedelta(days=newdays)).isoformat() if remaining<=0 else (oldexp+timedelta(days=extra)).isoformat()
        db=get_connection(); db.execute('UPDATE bots SET plan_key=?,plan_name=?,price=?,expires_at=? WHERE id=?',(key,newname,newprice,exp,bid)); db.commit(); db.close(); await bot_manage(q,bid); return
    if d.startswith('renew:'):
        bid=int(d.split(':')[1]); b=get_bot(bid); usr=user_row(uid)
        if not b or b['user_id']!=usr['id']: return
        price=int(b['price']);
        if usr['balance']<price: await q.edit_message_text(f'❌ موجودی کافی نیست.\nکمبود: {money(price-usr["balance"])}',reply_markup=kb([[btn('💰 کیف پول','wallet')],[btn('↩️ بازگشت',f'bot:{bid}')]])); return
        plan=get_plan(b['plan_key']); renew_days=plan[2] if plan else 30
        set_balance(usr['id'],-price,'license_renewal',b['plan_name']); base=datetime.fromisoformat(b['expires_at']) if b['expires_at'] and datetime.fromisoformat(b['expires_at'])>now() else now(); exp=(base+timedelta(days=renew_days)).isoformat(); db=get_connection(); db.execute('UPDATE bots SET expires_at=?,status=\"active\" WHERE id=?',(exp,bid)); db.commit(); db.close(); await start_instance(bid); await bot_manage(q,bid); return
    if d.startswith('import_backup:'):
        bid=int(d.split(':')[1]); b=get_bot(bid)
        if b and b['user_id']==user_row(uid)['id']: c.user_data.clear(); c.user_data.update({'state':'import_backup','bot_id':bid}); await q.edit_message_text('📥 فایل SQL بکاپ ربات را ارسال کن.');
        return
    if d.startswith('approve:') and admin(uid):
        oid=int(d.split(':')[1]); db=get_connection(); o=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone();
        if not o or o['status']!='pending_review': db.close(); return
        # Reserve wallet only now, exactly once.
        if o['wallet_amount']:
            urow=db.execute('SELECT balance FROM users WHERE id=?',(o['user_id'],)).fetchone()
            if not urow or urow['balance']<o['wallet_amount']: db.close(); await edit_callback_message(q, '❌ موجودی کیف پول کاربر دیگر کافی نیست.'); return
            db.execute('UPDATE users SET balance=balance-? WHERE id=?',(o['wallet_amount'],o['user_id'])); db.execute('INSERT INTO transactions(user_id,amount,type,description,order_id) VALUES(?,?,?,?,?)',(o['user_id'],-o['wallet_amount'],'license_purchase','خرید لایسنس',oid))
        db.execute("UPDATE orders SET status='paid',approved_by=?,approved_at=? WHERE id=?",(uid,now().isoformat(),oid)); db.commit(); db.close()
        await edit_callback_message(q, '🟢 پرداخت تأیید شد.')
        o2=get_order_row(oid)
        await c.bot.send_message(usr_tid(o2['user_id']), '🟢 پرداخت شما تأیید شد. حالا اطلاعات ربات را وارد کن.', reply_markup=kb([[btn('🤖 ادامه ساخت','continue_order:'+str(oid),'success')]]))
        return
    if d.startswith('reject:') and admin(uid):
        oid=int(d.split(':')[1]); db=get_connection(); db.execute("UPDATE orders SET status='rejected',rejected_by=?,rejected_at=? WHERE id=? AND status='pending_review'",(uid,now().isoformat(),oid)); o=db.execute('SELECT user_id FROM orders WHERE id=?',(oid,)).fetchone(); db.commit(); db.close(); await edit_callback_message(q, '🔴 پرداخت رد شد.');
        if o: await c.bot.send_message(get_user(o['user_id'])['telegram_id'],'❌ رسید پرداخت شما رد شد.'); return

# ---------- order provisioning ----------
def get_order_row(oid):
    db=get_connection(); r=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); db.close(); return dict(r) if r else None
def usr_tid(uid):
    u=get_user(uid); return u['telegram_id'] if u else 0

async def create_bot_from_order(context,oid):
    db=get_connection(); o=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); usr=db.execute('SELECT * FROM users WHERE id=?',(o['user_id'],)).fetchone(); db.close()
    if not o or not usr: return
    # For shortage flow, token/admin arrive after approval; move order into user_data is unsafe across restarts.
    # This function is intentionally only used by wallet-complete orders in this build.
    await context.bot.send_message(usr['telegram_id'],'🟢 پرداخت تأیید شد. حالا Admin ID و Bot Token را برای ساخت Instance ارسال کن.',reply_markup=kb([[btn('🤖 ادامه ساخت','build')]]))

# ---------- messages ----------
async def message(u,c):
    x=u.effective_user; txt=(u.message.text or '').strip(); st=c.user_data.get('state')
    if is_blocked((get_user_by_tid(x.id) or {}).get('id',-1)): return
    if st=='change_admin':
        if not txt.isdigit(): await u.message.reply_text('❌ فقط عدد.'); return
        bid=c.user_data['bot_id']; b=get_bot(bid)
        if not b or b['user_id']!=user_row(x.id)['id']: return
        db=get_connection(); db.execute('UPDATE bots SET admin_id=? WHERE id=?',(int(txt),bid)); db.commit(); db.close();        envp=Path(b['instance_path'])/'.env'; envp.write_text(f'BOT_TOKEN={b["bot_token"]}\nOWNER_ID={txt}\nAPP_NAME=PasarGuard Dealer\nLOG_LEVEL=INFO\n',encoding='utf-8'); await stop_instance(bid); await start_instance(bid); c.user_data.clear(); await u.message.reply_text('✅ Admin ID تغییر کرد.',reply_markup=home(x.id)); return
    if st=='change_token':
        try:
            me=await asyncio.to_thread(validate_token,txt)
            assert_not_store_token(txt,me)
        except Exception as e: await u.message.reply_text('❌ '+(str(e) if isinstance(e,ValueError) else 'توکن نامعتبر است.')); return
        bid=c.user_data['bot_id']; b=get_bot(bid)
        if not b or b['user_id']!=user_row(x.id)['id']: return
        db=get_connection(); db.execute('UPDATE bots SET bot_token=?,bot_username=?,telegram_bot_id=? WHERE id=?',(protect_token(txt),'@'+me['username'],me['id'],bid)); db.commit(); db.close(); envp=Path(b['instance_path'])/'.env'; envp.write_text(f'BOT_TOKEN={txt}\nOWNER_ID={b["admin_id"]}\nAPP_NAME=PasarGuard Dealer\nLOG_LEVEL=INFO\n',encoding='utf-8'); await stop_instance(bid); await start_instance(bid); c.user_data.clear(); await u.message.reply_text('✅ Token تغییر کرد و ربات دوباره اجرا شد.',reply_markup=home(x.id)); return
    if st=='transfer':
        if not txt.isdigit(): await u.message.reply_text('❌ فقط عدد.'); return
        bid=c.user_data['bot_id']; b=get_bot(bid); target=int(txt)
        if not b or b['user_id']!=user_row(x.id)['id']: return
        db=get_connection(); db.execute('UPDATE bots SET user_id=? WHERE id=?',(user_row(target)['id'] if get_user_by_tid(target) else upsert_user(target,'','')['id'],bid)); db.commit(); db.close(); c.user_data.clear(); await u.message.reply_text('✅ مالکیت ربات منتقل شد.',reply_markup=home(x.id)); return
    if st=='import_backup':
        doc=u.message.document
        if not doc or not doc.file_name.lower().endswith('.json'): await u.message.reply_text('❌ فقط بکاپ JSON صادرشده توسط Eleven Store را قبول می‌کنیم.'); return
        bid=c.user_data['bot_id']; b=get_bot(bid)
        if not b or b['user_id']!=user_row(x.id)['id']: return
        tmp=Path(tempfile.mkstemp(suffix='.json')[1])
        try:
            f=await doc.get_file(); await f.download_to_drive(str(tmp)); snap=json.loads(tmp.read_text(encoding='utf-8'))
            if snap.get('format')!='eleven-store-config-backup' or int(snap.get('version',0))<2: raise ValueError('فرمت بکاپ معتبر نیست.')
            dbpath=Path(b['instance_path'])/'database'/'app.db'
            if not dbpath.exists(): raise ValueError('دیتابیس Instance پیدا نشد.')
            conn=sqlite3.connect(dbpath); conn.row_factory=sqlite3.Row; conn.execute('BEGIN IMMEDIATE')
            tables=snap.get('tables',{})
            for table in ('settings','products','custom_settings','payment_methods'):
                rows=tables.get(table,[])
                if not rows: continue
                cols=sorted(rows[0].keys())
                if table=='settings': conn.execute('DELETE FROM settings')
                elif table=='products': conn.execute('DELETE FROM products')
                elif table=='custom_settings': conn.execute('DELETE FROM custom_settings')
                elif table=='payment_methods': conn.execute('DELETE FROM payment_methods')
                for row in rows:
                    conn.execute('INSERT INTO '+table+'('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[row.get(k) for k in cols])
            conn.commit(); conn.close(); c.user_data.clear(); await u.message.reply_text('✅ بکاپ تنظیمات با موفقیت برگردانده شد. سورس کد، فایل اجرایی یا امکان ساخت ربات از بکاپ منتقل نمی‌شود.')
        except Exception as e:
            try:
                conn.rollback(); conn.close()
            except Exception: pass
            await u.message.reply_text('❌ وارد کردن بکاپ انجام نشد: '+str(e)[:500])
        finally: tmp.unlink(missing_ok=True)
        return
    if st=='admin_id':
        if not txt.isdigit(): await u.message.reply_text('❌ Admin ID باید فقط عدد باشد.'); return
        c.user_data['admin_id']=int(txt); await ask_token_from_message(u,c); return
    if st=='bot_token':
        try:
            me=await asyncio.to_thread(validate_token,txt)
            assert_not_store_token(txt,me)
        except Exception as e: await u.message.reply_text('❌ '+(str(e) if isinstance(e,ValueError) else 'توکن نامعتبر است.')+' دوباره ارسال کن.'); return
        c.user_data['bot_token']=txt; c.user_data['bot_username']='@'+me['username'];
        if c.user_data.get('trial_mode'):
            await u.message.reply_text('🔍 اطلاعات تست آماده است.\n\n🤖 ربات: @'+me['username']+'\n⏱ مدت: ۲ ساعت\n\nبرای ساخت تست، گزینه زیر را بزنید.',reply_markup=kb([[btn('🎁 ساخت تست رایگان','trial_provision','success')],[btn('↩️ بازگشت','home')]])); return
        await review_from_message(u,c); return
    if st=='topup_amount':
        if not txt.isdigit() or int(txt)<=0: await u.message.reply_text('❌ مبلغ نامعتبر است.'); return
        amount=int(txt); card=get_method()
        if not card: await u.message.reply_text('❌ در حال حاضر کارت پرداخت تنظیم نشده است.',reply_markup=home(u.effective_user.id)); return
        c.user_data['topup_amount']=amount; c.user_data['topup_started_at']=now().isoformat(); c.user_data['state']='topup_waiting_payment'
        text=(f'💳 افزایش موجودی\n\nبرای افزایش موجودی، مبلغ {money(amount)} را به شماره حساب زیر واریز کنید 👇🏻\n\n'
              f'<code>{card["card_number"]}</code>\n👤 {card["card_holder"]}\n\n'
              '❌ این تراکنش به مدت یک ساعت اعتبار دارد؛ پس از آن امکان پرداخت این تراکنش وجود ندارد.\n'
              '‼️ مبلغ باید دقیقاً همان مبلغ ذکرشده باشد.\n'
              '‼️ امکان برداشت وجه از کیف پول وجود ندارد.\n'
              '‼️ مسئولیت واریز اشتباه بر عهده شماست.\n\n'
              '🔝 بعد از پرداخت، دکمه «پرداخت کردم» را بزنید و سپس تصویر رسید را ارسال کنید.\n'
              '💵 پس از تأیید پرداخت توسط ادمین، کیف پول شما شارژ خواهد شد.')
        await u.message.reply_text(text,parse_mode='HTML',reply_markup=kb([[btn('💳 پرداخت کردم','topup_paid','success')],[btn('↩️ لغو','wallet')]])); return
    if st=='card_number' and admin(x.id): c.user_data['card_number']=txt; c.user_data['state']='card_holder'; await u.message.reply_text('👤 نام صاحب کارت را ارسال کن.'); return
    if st=='card_holder' and admin(x.id): add_method(c.user_data['card_number'],txt,False,5); c.user_data.clear(); await u.message.reply_text('✅ کارت ثبت شد و به‌عنوان کارت فعال قرار گرفت.',reply_markup=kb([[btn('💳 کارت‌ها','a_cards')],[btn('👑 ادمین','admin')]])); return
    if st=='user_search' and admin(x.id):
        if not txt.isdigit(): await u.message.reply_text('❌ فقط آیدی عددی تلگرام.'); return
        found=get_user_by_tid(int(txt)); c.user_data.clear()
        if not found: await u.message.reply_text('❌ کاربری با این آیدی پیدا نشد.',reply_markup=kb([[btn('↩️ کاربران','a_users')]])); return
        await u.message.reply_text(user_detail_text(found),parse_mode='HTML',reply_markup=kb([[btn('➕ افزایش موجودی',f'ubal_add:{found["id"]}','success'),btn('➖ کاهش موجودی',f'ubal_sub:{found["id"]}','danger')],[btn('🔓 رفع مسدودی' if is_blocked(found['id']) else '🔒 مسدود کردن',f'uunblock:{found["id"]}' if is_blocked(found['id']) else f'ublock:{found["id"]}')],[btn('↩️ کاربران','a_users')]])); return
    if st=='ubal_amount' and admin(x.id):
        if not txt.isdigit() or int(txt)<=0: await u.message.reply_text('❌ مبلغ نامعتبر است.'); return
        amount=int(txt); c.user_data['ubal_amount']=amount; sign=c.user_data.get('ubal_sign',1); tgt=c.user_data.get('ubal_uid'); tu=get_user(tgt) if tgt else None
        word='افزایش' if sign>0 else 'کاهش'
        await u.message.reply_text(f'⚠️ تأیید عملیات مالی\n\n👤 کاربر: {tu["telegram_id"] if tu else tgt}\n💰 {word} موجودی به مبلغ: {money(amount)}\n\nآیا مطمئنی؟',reply_markup=kb([[btn('🟢 تأیید','ubal_confirm','success'),btn('🔴 لغو','ubal_cancel','danger')]])); return
    if st=='prod_name' and admin(x.id):
        c.user_data['p_name']=txt; c.user_data['state']='prod_price'
        await u.message.reply_text('💰 قیمت محصول را به تومان ارسال کن.'); return
    if st=='prod_price' and admin(x.id):
        if not txt.isdigit() or int(txt)<0: await u.message.reply_text('❌ فقط عدد صفر یا بیشتر.'); return
        c.user_data['p_price']=int(txt); c.user_data['state']='prod_gb'
        await u.message.reply_text('📊 حجم محصول را به گیگ ارسال کن.\n\nعدد 0 یعنی حجم نامحدود.'); return
    if st=='prod_gb' and admin(x.id):
        if not txt.isdigit() or int(txt)<0: await u.message.reply_text('❌ حجم نامعتبر است.'); return
        c.user_data['p_gb']=int(txt); c.user_data['state']='prod_days'
        await u.message.reply_text('📅 مدت محصول را به روز ارسال کن.\n\nعدد 0 یعنی مدت نامحدود.'); return
    if st=='prod_days' and admin(x.id):
        if not txt.isdigit() or int(txt)<0: await u.message.reply_text('❌ مدت نامعتبر است.'); return
        days=int(txt); gb=int(c.user_data.get('p_gb',0))
        if gb==0 and days==0: await u.message.reply_text('❌ حجم و مدت نمی‌توانند هر دو نامحدود باشند.'); return
        c.user_data['p_days']=days; c.user_data['state']='prod_users'
        await u.message.reply_text('👥 حداکثر تعداد کاربر را ارسال کن.\n\nعدد 0 یعنی نامحدود.'); return
    if st=='prod_users' and admin(x.id):
        if not txt.isdigit() or int(txt)<0: await u.message.reply_text('❌ تعداد کاربر نامعتبر است.'); return
        c.user_data['p_users']=int(txt); c.user_data['state']='prod_capacity'
        await u.message.reply_text('📦 ظرفیت فروش را ارسال کن.\n\nعدد 0 یعنی فروش نامحدود.'); return
    if st=='prod_capacity' and admin(x.id):
        if not txt.isdigit() or int(txt)<0: await u.message.reply_text('❌ ظرفیت نامعتبر است.'); return
        c.user_data['p_capacity']=int(txt); c.user_data['state']='prod_desc'
        await u.message.reply_text('📝 توضیحات محصول را ارسال کن (یا "-" برای رد کردن).'); return
    if st=='prod_desc' and admin(x.id):
        desc='' if txt=='-' else txt
        d=c.user_data
        p=create_product(d['p_name'],d['p_gb'],d['p_days'],d['p_users'],d['p_price'],desc,d['p_capacity'])
        c.user_data.clear()
        await u.message.reply_text(f'✅ محصول ساخته شد.\n\n📦 {p["name"]}\n💰 {money(p["price"])}\n📊 حجم: {"نامحدود" if not p["data_gb"] else str(p["data_gb"])+" گیگ"}\n📅 مدت: {"نامحدود" if not p["days"] else str(p["days"])+" روز"}',reply_markup=kb([[btn('🛒 محصولات','a_products')]])); return
    if st=='edit_prod_field' and admin(x.id):
        pid=c.user_data['edit_pid']; field=c.user_data['edit_field']
        if field in ('price','days','data_gb','max_users','capacity') and (not txt.isdigit() or int(txt)<0):
            await u.message.reply_text('❌ فقط عدد صفر یا بیشتر.'); return
        value=int(txt) if field in ('price','days','data_gb','max_users','capacity') else txt
        if field in ('data_gb','days') and int(value)==0:
            other=get_product(pid)
            if other:
                other_value=int(other['days'] if field=='data_gb' else other['data_gb'])
                if other_value==0:
                    await u.message.reply_text('❌ حجم و مدت نمی‌توانند هر دو نامحدود باشند.'); return
        update_product(pid,**{field:value}); c.user_data.clear(); await u.message.reply_text('✅ محصول به‌روزرسانی شد.',reply_markup=kb([[btn('↩️ محصولات','a_products')]])); return
    if st=='edit_text_key' and admin(x.id):
        key=c.user_data['edit_key']; save_setting(key,txt); c.user_data.clear(); await u.message.reply_text('✅ متن ذخیره شد.',reply_markup=kb([[btn('↩️ مدیریت متن‌ها','a_texts')]])); return
    if st=='support_msg':
        usr=user_row(x.id); ticket=get_open_ticket(usr['id']) or create_ticket(usr['id'])
        add_message(ticket['id'],'user',txt)
        header=f'🆘 تیکت #{ticket["id"]} | وضعیت: باز\n👤 {x.first_name or "-"} | @{x.username or "-"} | 🆔 {x.id}\n\n💬 {txt}'
        try:
            sent=await c.bot.send_message(OWNER_ID,header,reply_markup=kb([[btn('🔵 پاسخ',f'ticket_reply:{ticket["id"]}'),btn('🔒 بستن تیکت',f'ticket_close:{ticket["id"]}','danger')]]))
        except Exception: sent=None
        await u.message.reply_text('✅ پیام شما برای پشتیبانی ارسال شد. می‌توانید پیام‌های بیشتری هم ارسال کنید؛ به محض پاسخ ادمین به شما اطلاع داده می‌شود.',reply_markup=kb([[btn('↩️ منوی اصلی','home')]])); return
    if st=='ticket_reply' and admin(x.id):
        tid=c.user_data['ticket_id']; t=get_ticket(tid)
        if not t or t['status']!='open': await u.message.reply_text('❌ این تیکت باز نیست.'); c.user_data.clear(); return
        add_message(tid,'admin',txt); tu=get_user(t['user_id']); c.user_data.clear()
        if tu:
            try: await c.bot.send_message(tu['telegram_id'],f'🔵 پاسخ پشتیبانی:\n\n{txt}')
            except Exception: pass
        await u.message.reply_text('✅ پاسخ ارسال شد.',reply_markup=kb([[btn('🆘 پشتیبانی','a_support')]])); return

async def photo_or_doc(u,c):
    if c.user_data.get('state')=='awaiting_receipt': await receipt(u,c); return
    if c.user_data.get('state')=='topup_receipt':
        started=c.user_data.get('topup_started_at')
        if started:
            try:
                if now()-datetime.fromisoformat(started) > timedelta(hours=1):
                    c.user_data.clear(); await u.message.reply_text('❌ مهلت این تراکنش تمام شده است. دوباره از بخش افزایش موجودی درخواست جدید ایجاد کن.',reply_markup=home(u.effective_user.id)); return
            except Exception: pass
        file_id=u.message.photo[-1].file_id if u.message.photo else u.message.document.file_id if u.message.document else None
        if not file_id: return
        usr=user_row(u.effective_user.id); amount=c.user_data['topup_amount']; db=get_connection(); cur=db.execute('INSERT INTO wallet_topups(user_id,amount,status,receipt_file_id,receipt_message_id) VALUES(?,?,?,?,?)',(usr['id'],amount,'pending_review',file_id,u.message.message_id)); tid=cur.lastrowid; db.commit(); db.close()
        caption=f'💰 درخواست شارژ کیف پول #{tid}\n\n👤 کاربر: {u.effective_user.id}\n💵 مبلغ: {money(amount)}\n💳 درخواست افزایش موجودی'
        buttons=kb([[btn('🟢 تأیید',f'topup_ok:{tid}','success'),btn('🔴 رد',f'topup_no:{tid}','danger')]])
        if u.message.photo:
            await c.bot.send_photo(OWNER_ID,file_id,caption=caption,reply_markup=buttons)
        elif u.message.document:
            await c.bot.send_document(OWNER_ID,file_id,caption=caption,reply_markup=buttons)
        else:
            await c.bot.send_message(OWNER_ID,caption,reply_markup=buttons)
        c.user_data.clear(); await u.message.reply_text('✅ رسید شارژ ارسال شد. بعد از تأیید ادمین، کیف پولت شارژ می‌شود.',reply_markup=home(u.effective_user.id))

async def ask_token_from_message(u,c): c.user_data['state']='bot_token'; await u.message.reply_text('🔑 Bot Token را ارسال کن.');
async def review_from_message(u,c): await u.message.reply_text(f'🔍 اطلاعات آماده است:\n\n📦 {c.user_data["plan_name"]}\n💰 {money(c.user_data["price"])}\n🆔 Admin ID: {c.user_data["admin_id"]}\n🤖 @{c.user_data.get("bot_username", "-")}',reply_markup=kb([[btn('🟢 ساخت و راه‌اندازی','provision','success')],[btn('↩️ بازگشت','build')]]))

async def _send_expiry_notice(bot,b,days_left,interval_key):
    c=get_connection()
    try:
        c.execute('INSERT OR IGNORE INTO expiry_notifications(bot_id,bucket) VALUES(?,?)',(b['id'],interval_key))
        if c.total_changes!=1: c.rollback(); return False
        c.commit()
    finally: c.close()
    try:
        await bot.send_message(usr_tid(b['user_id']),f'⚠️ هشدار انقضا\n\n🤖 ربات: @{b["bot_username"] or "-"}\n📦 لایسنس: {b["plan_name"]}\n📅 فقط {days_left} روز تا انقضا باقی مانده است.\n⏰ لطفاً برای تمدید اقدام کن.')
        return True
    except Exception:
        c=get_connection(); c.execute('DELETE FROM expiry_notifications WHERE bot_id=? AND bucket=?',(b['id'],interval_key)); c.commit(); c.close(); return False

async def job_expiry(context):
    current=now(); db=get_connection(); rows=db.execute("SELECT * FROM bots WHERE status IN ('active','starting','stopped','error','expired') AND expires_at IS NOT NULL").fetchall(); db.close()
    for raw in rows:
        b=dict(raw)
        try: exp=datetime.fromisoformat(b['expires_at'])
        except Exception: continue
        seconds=(exp-current).total_seconds()
        if 0 < seconds <= 7*86400:
            if seconds > 86400:
                await _send_expiry_notice(context.bot,b,max(1,int((seconds+86399)//86400)),f'daily-{exp.date().isoformat()}')
            else:
                await _send_expiry_notice(context.bot,b,1,f'hour2-{int(seconds//7200)}')
        if seconds <= 0 and b['status'] not in ('expired','deleted'):
            if b.get('plan_key') == 'trial':
                try: path=await backup_bot(b['id'],'trial-expiry')
                except Exception as e: path=None; log.exception('trial backup failed: %s',e)
                try: await stop_instance(b['id'])
                except Exception: pass
                if path:
                    try:
                        with open(path,'rb') as f: await context.bot.send_document(usr_tid(b['user_id']),f,filename=path.name,caption='⏰ تست رایگان ۲ ساعته شما به پایان رسید.\n\n💾 بکاپ تنظیمات پیوست شد.\n🗑 نمونه آزمایشی به‌طور کامل حذف شد.')
                    except Exception: log.exception('trial backup delivery failed')
                shutil.rmtree(b['instance_path'],ignore_errors=True)
                db=get_connection(); db.execute("UPDATE bots SET status='deleted',process_pid=NULL,deleted_at=?,expired_at=COALESCE(expired_at,?) WHERE id=?",(current.isoformat(),current.isoformat(),b['id'])); db.commit(); db.close(); audit('trial_deleted',b['user_id'],'trial bot cleanup')
                continue
            try: path=await backup_bot(b['id'],'expiry')
            except Exception as e: path=None; log.exception('expiry backup failed: %s',e)
            try: await stop_instance(b['id'])
            except Exception: pass
            db=get_connection(); db.execute("UPDATE bots SET status='expired',process_pid=NULL,expired_at=COALESCE(expired_at,?) WHERE id=?",(current.isoformat(),b['id'])); db.commit(); db.close()
            if path:
                try:
                    with open(path,'rb') as f: await context.bot.send_document(usr_tid(b['user_id']),f,filename=path.name,caption=f'⏰ لایسنس منقضی شد\n🤖 ربات: @{b["bot_username"] or "-"}\n📦 پلن: {b["plan_name"]}\n📅 زمان انقضا: {b["expires_at"]}\n🛑 ربات خاموش شد و تا ۳ روز نگهداری می‌شود.\n\n💾 بکاپ تنظیمات پیوست شد؛ سورس کد و فایل اجرایی داخل بکاپ نیست.')
                except Exception: log.exception('expiry backup delivery failed')
        elif b['status']=='expired' and b.get('expired_at'):
            try: expired_at=datetime.fromisoformat(b['expired_at'])
            except Exception: continue
            if current-expired_at >= timedelta(days=3):
                try: await stop_instance(b['id'])
                except Exception: pass
                shutil.rmtree(b['instance_path'],ignore_errors=True)
                db=get_connection(); db.execute("UPDATE bots SET status='deleted',process_pid=NULL,deleted_at=? WHERE id=? AND status='expired'",(current.isoformat(),b['id'])); db.commit(); db.close(); audit('license_retention_deleted',0,f'bot={b["id"]}')

async def error(u,c): log.exception('Unhandled bot error',exc_info=c.error)

def pid_alive(pid):
    if not pid: return False
    try: os.kill(pid,0)
    except (OSError,ProcessLookupError): return False
    except Exception: return False
    return True

async def resume_instances(app=None):
    """Rule #7 (اجرای خودکار Eleven Pro): on Store startup, find every customer
    Instance that was left active/starting and bring it back up. Never let a
    single broken instance crash the Store; record the error on that bot row
    instead and move on to the next one."""
    db=get_connection(); rows=db.execute("SELECT * FROM bots WHERE status IN ('active','starting')").fetchall(); db.close()
    if not rows: return
    log.info(f'Resuming {len(rows)} customer instance(s) from last run…')
    for b in rows:
        bid=b['id']
        if pid_alive(b['process_pid']):
            # Rule: an instance must never run twice at once — if the OS process
            # from before the restart is still alive, don't spawn a second one.
            log.warning(f'Instance {bid}: previous PID {b["process_pid"]} still alive, skipping re-launch.')
            continue
        try:
            await start_instance(bid)
            log.info(f'Instance {bid} resumed.')
        except Exception as e:
            log.exception(f'Instance {bid} failed to resume')
            db=get_connection(); db.execute("UPDATE bots SET status='error',last_error=? WHERE id=?",(f'اجرای خودکار هنگام راه‌اندازی Store شکست خورد: {str(e)[:400]}',bid)); db.commit(); db.close()

def main():
    global STORE_BOT_ID
    if not BOT_TOKEN or not OWNER_ID: raise RuntimeError('BOT_TOKEN و OWNER_ID را در .env تنظیم کنید.')
    try: STORE_BOT_ID=validate_token(BOT_TOKEN)['id']
    except Exception: log.warning('Could not resolve the Store bot\'s own Telegram ID at startup; token-reuse checks will fall back to string comparison only.')
    app=Application.builder().token(BOT_TOKEN).post_init(resume_instances).build(); app.add_handler(CommandHandler('start',start)); app.add_handler(CallbackQueryHandler(callback)); app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO,photo_or_doc)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,message)); app.add_error_handler(error)
    if app.job_queue: app.job_queue.run_repeating(job_expiry,interval=300,first=20)
    app.run_polling()
if __name__=='__main__': main()
