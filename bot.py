import os, sqlite3, secrets, string, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
BASE=Path(__file__).resolve().parent; DB=BASE/'data'/'eleven_store.db'; INSTANCES=BASE/'instances'; TEMPLATE=BASE/'customer_template'; BACKUPS=BASE/'backups'
for p in (DB.parent,INSTANCES,BACKUPS): p.mkdir(parents=True,exist_ok=True)
load_dotenv(BASE/'.env'); BOT_TOKEN=os.getenv('BOT_TOKEN','').strip(); OWNER_ID=int(os.getenv('OWNER_ID','0') or 0)
PLANS={'1m':('لایسنس ۱ ماهه',250000,30),'2m':('لایسنس ۲ ماهه',500000,60),'3m':('لایسنس ۳ ماهه',699000,90)}
def db(): c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def now(): return datetime.now()
def money(x): return f'{int(x):,} تومان'
def kb(rows): return InlineKeyboardMarkup([[InlineKeyboardButton(t,callback_data=d) for t,d in r] for r in rows])
def home(uid):
    rows=[[('🤖 ساخت ربات','build'),('💰 کیف پول','wallet')],[('⚙️ مدیریت ربات','manage'),('🆘 پشتیبانی','support')],[('👥 زیرمجموعه‌گیری','ref')]]
    if uid==OWNER_ID: rows.append([('👑 پنل ادمین','admin')])
    return kb(rows)
def init_db():
    c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,telegram_id INTEGER UNIQUE,username TEXT,balance INTEGER DEFAULT 0,created_at TEXT);CREATE TABLE IF NOT EXISTS bots(id INTEGER PRIMARY KEY,user_id INTEGER,bot_username TEXT,bot_token TEXT,admin_id INTEGER,plan TEXT,plan_price INTEGER,expires_at TEXT,status TEXT,instance_path TEXT,last_backup TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,key TEXT UNIQUE,name TEXT,price INTEGER,duration_days INTEGER,active INTEGER DEFAULT 1);CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,user_id INTEGER,bot_id INTEGER,plan_key TEXT,token TEXT,admin_id INTEGER,amount INTEGER,wallet_amount INTEGER DEFAULT 0,card_amount INTEGER DEFAULT 0,status TEXT,receipt_file_id TEXT,created_at TEXT,approved_at TEXT,rejected_at TEXT,error TEXT);CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY,number TEXT,holder TEXT,active INTEGER DEFAULT 1,is_default INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY,user_id INTEGER,amount INTEGER,type TEXT,description TEXT,order_id INTEGER,created_at TEXT);CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY,user_id INTEGER,message TEXT,status TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE,invited_count INTEGER DEFAULT 0,earned INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS texts(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS backups(id INTEGER PRIMARY KEY,user_id INTEGER,bot_id INTEGER,path TEXT,kind TEXT,created_at TEXT);''')
    
    for col,typ in [('token','TEXT'),('admin_id','INTEGER')]:
        try:c.execute(f'ALTER TABLE orders ADD COLUMN {col} {typ}')
        except sqlite3.OperationalError:pass
    for k,(n,p,d) in PLANS.items(): c.execute('INSERT OR IGNORE INTO products(key,name,price,duration_days) VALUES(?,?,?,?)',(k,n,p,d))
    c.commit(); c.close()
def user(u):
    c=db(); c.execute('INSERT INTO users(telegram_id,username,created_at) VALUES(?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username',(u.id,u.username or '',now().isoformat())); c.execute('INSERT OR IGNORE INTO referrals(user_id) SELECT id FROM users WHERE telegram_id=?',(u.id,)); c.commit(); r=c.execute('SELECT * FROM users WHERE telegram_id=?',(u.id,)).fetchone(); c.close(); return r
def get_bot(bid,uid=None):
    c=db(); q='SELECT * FROM bots WHERE id=?'; a=[bid]
    if uid is not None:q+=' AND user_id=?';a.append(uid)
    r=c.execute(q,a).fetchone();c.close();return r
def validate_token(token):
    try:r=requests.get(f'https://api.telegram.org/bot{token}/getMe',timeout=12);j=r.json();return j.get('ok'),j.get('result',{})
    except:return False,{}
def stop_instance(path):
    if not path:return
    f=Path(path)/'instance.pid'
    if f.exists():
        try:
            pid=int(f.read_text().strip())
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:os.kill(pid,15)
        except:pass
        try:f.unlink()
        except:pass
def start_instance(path,token,owner):
    p=Path(path); out=open(p/'runtime.log','a',encoding='utf8'); env=os.environ.copy(); env.update(BOT_TOKEN=token,OWNER_ID=str(owner),ADMIN_ID=str(owner)); proc=subprocess.Popen([sys.executable,'main.py'],cwd=str(p),env=env,stdout=out,stderr=subprocess.STDOUT); (p/'instance.pid').write_text(str(proc.pid)); return proc
def sql_backup(b):
    src=Path(b['instance_path'])/'database'/'app.db'
    if not src.exists():return None
    out=BACKUPS/f'bot-{b["id"]}-{datetime.now():%Y%m%d-%H%M%S}.sql'; s=sqlite3.connect(src); f=open(out,'w',encoding='utf8')
    for line in s.iterdump():f.write(line+'\n')
    f.close();s.close();return out
def record_backup(b):
    path=sql_backup(b)
    if not path:return None
    c=db();c.execute('UPDATE bots SET last_backup=? WHERE id=?',(now().isoformat(),b['id']));c.execute('INSERT INTO backups(user_id,bot_id,path,kind,created_at) VALUES(?,?,?,?,?)',(b['user_id'],b['id'],str(path),'sql',now().isoformat()));c.commit();c.close();return path
def change_balance(uid,amount,typ,desc,oid=None):
    c=db();c.execute('UPDATE users SET balance=balance+? WHERE id=?',(amount,uid));c.execute('INSERT INTO transactions(user_id,amount,type,description,order_id,created_at) VALUES(?,?,?,?,?,?)',(uid,amount,typ,desc,oid,now().isoformat()));c.commit();c.close()
def provision(uid,aid,token,key):
    name,price,dur=PLANS[key];p=INSTANCES/f'bot-{uid}-{int(time.time()*1000)}';p.mkdir(parents=True)
    for src in TEMPLATE.rglob('*'):
        rel=src.relative_to(TEMPLATE);dst=p/rel
        if src.is_dir():dst.mkdir(parents=True,exist_ok=True)
        elif '__pycache__' not in src.parts and src.name not in ('.env','.env.example','README.txt'):shutil.copy2(src,dst)
    (p/'.env').write_text(f'BOT_TOKEN={token}\nOWNER_ID={aid}\nAPP_NAME=Eleven Store Dealer\nLOG_LEVEL=INFO\n',encoding='utf8')
    ok,res=validate_token(token)
    if not ok:shutil.rmtree(p,ignore_errors=True);raise ValueError('Bot Token معتبر نیست.')
    proc=start_instance(p,token,aid);time.sleep(2)
    if proc.poll() is not None:
        log=(p/'runtime.log').read_text(encoding='utf8',errors='replace')[-1500:] if (p/'runtime.log').exists() else '';shutil.rmtree(p,ignore_errors=True);raise RuntimeError('Instance اجرا نشد.\n'+log)
    exp=now()+timedelta(days=dur);c=db();c.execute('INSERT INTO bots(user_id,bot_username,bot_token,admin_id,plan,plan_price,expires_at,status,instance_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,'@'+res.get('username',''),token,aid,name,price,exp.isoformat(),'active',str(p),now().isoformat()));bid=c.lastrowid;c.execute('INSERT INTO orders(user_id,bot_id,plan_key,amount,status,created_at,approved_at) VALUES(?,?,?,?,?,?,?)',(uid,bid,key,price,'paid',now().isoformat(),now().isoformat()));c.commit();c.close();return bid
async def start(update,ctx):user(update.effective_user);await update.message.reply_text('👋 به Eleven Store خوش اومدی!\n\nاز منوی زیر لایسنس ربات فروش پنل رو تهیه و مدیریت کن.',reply_markup=home(update.effective_user.id))
async def back(q):await q.edit_message_text('🏠 منوی اصلی',reply_markup=home(q.from_user.id))
async def build(q,ctx):ctx.user_data.clear();await q.edit_message_text('🤖 ساخت ربات\n\n📦 لایسنس موردنظر را انتخاب کن:',reply_markup=kb([[('🟢 لایسنس ۱ ماهه — ۲۵۰,۰۰۰ تومان','plan:1m')],[('🟢 لایسنس ۲ ماهه — ۵۰۰,۰۰۰ تومان','plan:2m')],[('🟢 لایسنس ۳ ماهه — ۶۹۹,۰۰۰ تومان','plan:3m')],[('🔙 بازگشت','back')]]))
async def wallet(q,ctx):u=user(q.from_user);await q.edit_message_text(f'💰 کیف پول\n\n💵 موجودی: {u["balance"]:,} تومان',reply_markup=kb([[('➕ افزایش موجودی','topup')],[('📜 تراکنش‌ها','transactions')],[('🔙 بازگشت','back')]]))
async def manage(q,ctx):
    u=user(q.from_user);c=db();bs=c.execute('SELECT * FROM bots WHERE user_id=? ORDER BY id DESC',(u['id'],)).fetchall();c.close()
    if not bs:return await q.edit_message_text('⚙️ هنوز رباتی نداری.',reply_markup=kb([[('🤖 ساخت ربات','build'),('🔙 بازگشت','back')]]))
    await q.edit_message_text('⚙️ مدیریت ربات\n\nربات موردنظر را انتخاب کن:',reply_markup=kb([[(f'🤖 {b["bot_username"] or "ربات"}',f'bot:{b["id"]}')] for b in bs]+[[('🔙 بازگشت','back')]]))
async def bot_info(q,ctx,bid):
    b=get_bot(bid,q.from_user.id)
    if not b:return await q.edit_message_text('❌ ربات پیدا نشد.')
    await q.edit_message_text(f'🤖 اطلاعات ربات\n\n🤖 Username: {b["bot_username"]}\n🟢 وضعیت: {b["status"]}\n📦 لایسنس: {b["plan"]}\n🆔 Admin ID: {b["admin_id"]}\n📅 انقضا: {b["expires_at"]}\n💾 آخرین بکاپ: {b["last_backup"] or "هنوز گرفته نشده"}',reply_markup=kb([[('👤 تغییر ادمین',f'chgadmin:{bid}'),('🔑 تغییر توکن',f'chgtoken:{bid}')],[('💾 دریافت بکاپ',f'backup:{bid}'),('📥 وارد کردن بکاپ',f'import:{bid}')],[('🔀 انتقال ربات',f'transfer:{bid}'),('📦 تغییر لایسنس',f'changeplan:{bid}')],[('📅 تمدید ربات',f'renew:{bid}'),('🗑 حذف ربات',f'delete:{bid}')],[('🔙 بازگشت','manage')]]))
async def admin_menu(q):
    if q.from_user.id!=OWNER_ID:return await q.answer('دسترسی ندارید',show_alert=True)
    await q.edit_message_text('👑 پنل ادمین\n\nهمه بخش‌های مدیریتی Eleven Store:',reply_markup=kb([[('👥 کاربران','admin:users'),('🤖 ربات‌ها','admin:bots')],[('📦 لایسنس‌ها','admin:licenses'),('💳 پرداخت‌ها','admin:payments')],[('💰 کیف پول‌ها','admin:wallets'),('🎁 زیرمجموعه‌ها','admin:refs')],[('💾 بکاپ‌ها','admin:backups'),('🆘 پشتیبانی','admin:support')],[('🛒 محصولات','admin:products'),('✏️ مدیریت متن‌ها','admin:texts')],[('💳 کارت‌های بانکی','admin:cards'),('📊 گزارش‌ها','admin:reports')],[('⚙️ تنظیمات','admin:settings')],[('🔙 بازگشت','back')]]))
async def admin_action(q,ctx,d):
    if q.from_user.id!=OWNER_ID:return await q.answer('دسترسی ندارید',show_alert=True)
    a=d.split(':',1)[1];c=db()
    if a=='users':txt=f'👥 کاربران: {c.execute("SELECT COUNT(*) FROM users").fetchone()[0]}'
    elif a=='bots':txt=f'🤖 ربات‌ها: {c.execute("SELECT COUNT(*) FROM bots").fetchone()[0]}'
    elif a=='licenses':txt='📦 لایسنس‌ها\n\n'+'\n'.join(f'{r["name"]} — {r["price"]:,} تومان — {r["duration_days"]} روز' for r in c.execute('SELECT * FROM products').fetchall())
    elif a=='payments':txt='💳 پرداخت‌ها\n\n'+'\n'.join(f'#{r["id"]} | {r["amount"]:,} | {r["status"]}' for r in c.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 20').fetchall())
    elif a=='wallets':txt='💰 کیف پول‌ها\n\n'+'\n'.join(f'{r["telegram_id"]} — {r["balance"]:,}' for r in c.execute('SELECT * FROM users ORDER BY balance DESC LIMIT 20').fetchall())
    elif a=='refs':txt='🎁 زیرمجموعه‌ها\n\n'+'\n'.join(f'{r["user_id"]} — {r["invited_count"]} دعوت — {r["earned"]:,}' for r in c.execute('SELECT * FROM referrals ORDER BY invited_count DESC LIMIT 20').fetchall())
    elif a=='backups':txt='💾 بکاپ‌ها\n\n'+'\n'.join(f'#{r["id"]} | bot {r["bot_id"]} | {r["created_at"]}' for r in c.execute('SELECT * FROM backups ORDER BY id DESC LIMIT 20').fetchall())
    elif a=='support':txt='🆘 تیکت‌ها\n\n'+'\n'.join(f'#{r["id"]} | user {r["user_id"]} | {r["status"]}\n{r["message"][:120]}' for r in c.execute('SELECT * FROM tickets ORDER BY id DESC LIMIT 20').fetchall())
    elif a=='products':txt='🛒 محصولات\n\nبرای ویرایش: 1m:250000:30';ctx.user_data['state']='admin_product'
    elif a=='texts':txt='✏️ مدیریت متن‌ها\n\nفرمت: کلید=متن';ctx.user_data['state']='admin_text'
    elif a=='cards':
        rows=c.execute('SELECT * FROM cards ORDER BY is_default DESC,id').fetchall();txt='💳 کارت‌های بانکی\n\n'+('\n'.join(f'#{r["id"]} | {r["number"]} | {r["holder"]} | پیش‌فرض={r["is_default"]}' for r in rows) if rows else 'کارتی ثبت نشده.')+'\n\nافزودن: شماره|نام صاحب کارت';ctx.user_data['state']='admin_card'
    elif a=='reports':txt=f'📊 گزارش‌ها\n\n👥 کاربران: {c.execute("SELECT COUNT(*) FROM users").fetchone()[0]}\n🤖 ربات‌ها: {c.execute("SELECT COUNT(*) FROM bots").fetchone()[0]}\n📦 سفارش‌ها: {c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]}'
    else:txt='⚙️ تنظیمات\n\nتنظیمات اصلی از .env خوانده می‌شوند.'
    c.close();await q.edit_message_text(txt,reply_markup=kb([[('🔙 بازگشت به ادمین','admin')]]))
async def cb(update,ctx):
    q=update.callback_query;await q.answer();d=q.data;uid=q.from_user.id
    if d=='back':return await back(q)
    if d=='build':return await build(q,ctx)
    if d=='wallet':return await wallet(q,ctx)
    if d=='manage':return await manage(q,ctx)
    if d.startswith('bot:'):return await bot_info(q,ctx,int(d.split(':')[1]))
    if d.startswith('plan:'):
        k=d.split(':')[1];n,p,_=PLANS[k];ctx.user_data.update(state='admin_id',plan_key=k,plan=n,plan_price=p);return await q.edit_message_text(f'📦 {n}\n💰 {money(p)}\n\n🆔 Admin ID را مشخص کن:',reply_markup=kb([[('🟢 همین اکانت','admin:self')],[('🔵 اکانت دیگر','admin:other')],[('🔙 بازگشت','build')]]))
    if d=='admin:self':ctx.user_data.update(admin_id=uid,state='token');return await q.edit_message_text(f'🆔 Admin ID: {uid}\n\n🔑 Bot Token را از @BotFather ارسال کن.')
    if d=='admin:other':ctx.user_data['state']='admin_other';return await q.edit_message_text('🆔 آیدی عددی ادمین جدید را ارسال کن.')
    if d=='topup':ctx.user_data['state']='topup';return await q.edit_message_text('💳 مبلغ شارژ کیف پول را به تومان ارسال کن.')
    if d=='transactions':
        u=user(q.from_user);c=db();rs=c.execute('SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 20',(u['id'],)).fetchall();c.close();return await q.edit_message_text('📜 تراکنش‌ها\n\n'+('\n'.join(f'#{r["id"]} | {r["amount"]:+,} | {r["description"]}' for r in rs) if rs else 'تراکنشی ثبت نشده.'),reply_markup=kb([[('🔙 بازگشت','wallet')]]))
    if d=='support':ctx.user_data['state']='support';return await q.edit_message_text('🆘 پیام پشتیبانی را ارسال کن.')
    if d=='ref':
        u=user(q.from_user);c=db();r=c.execute('SELECT * FROM referrals WHERE user_id=?',(u['id'],)).fetchone();c.close();me=await ctx.bot.get_me();return await q.edit_message_text(f'👥 زیرمجموعه‌گیری\n\n🔗 https://t.me/{me.username}?start=ref_{uid}\n\n👥 دعوت‌شده: {r["invited_count"]}\n🎁 درآمد: {r["earned"]:,} تومان',reply_markup=kb([[('🔙 بازگشت','back')]]))
    if d=='admin':return await admin_menu(q)
    if d.startswith('admin:'):return await admin_action(q,ctx,d)
    if d.startswith(('chgadmin:','chgtoken:','backup:','import:','transfer:','changeplan:','renew:','delete:')):
        a,b=d.split(':');ctx.user_data.update(state=a,bid=int(b));msg={'chgadmin':'🆔 Admin ID جدید را ارسال کن.','chgtoken':'🔑 Bot Token جدید را ارسال کن.','backup':'💾 بکاپ SQL ساخته و ارسال می‌شود.','import':'📥 فایل SQL بکاپ را ارسال کن.','transfer':'🔀 Admin ID مالک جدید را ارسال کن.','changeplan':'📦 کلید پلن جدید: 1m / 2m / 3m','renew':'📅 تعداد روز تمدید را ارسال کن.','delete':'🗑 برای حذف، «حذف» را ارسال کن.'}[a];return await q.edit_message_text(msg,reply_markup=kb([[('🔙 بازگشت','manage')]]))
async def text(update,ctx):
    t=(update.message.text or '').strip();st=ctx.user_data.get('state');u=user(update.effective_user)
    if st=='admin_other':
        if not t.isdigit():return await update.message.reply_text('❌ فقط عدد ارسال کن.')
        ctx.user_data.update(admin_id=int(t),state='token');return await update.message.reply_text('🔑 Bot Token را ارسال کن.')
    if st=='token':
        ok,res=validate_token(t)
        if not ok:return await update.message.reply_text('❌ Bot Token معتبر نیست.')
        ctx.user_data.update(bot_token=t,state='confirm');return await update.message.reply_text(f'🔍 بررسی اطلاعات\n\n🤖 @{res.get("username")}\n📦 {ctx.user_data["plan"]}\n🆔 {ctx.user_data["admin_id"]}',reply_markup=kb([[('🟢 تأیید و راه‌اندازی','provision')],[('🔴 لغو','back')]]))
    if st=='support':
        c=db();c.execute('INSERT INTO tickets(user_id,message,status,created_at) VALUES(?,?,?,?)',(u['id'],t,'open',now().isoformat()));c.commit();c.close();ctx.user_data.clear();return await update.message.reply_text('✅ پیام پشتیبانی ثبت شد.',reply_markup=home(u['telegram_id']))
    if st=='topup':
        try:a=int(t)
        except:return await update.message.reply_text('❌ مبلغ باید عدد باشد.')
        c=db();card=c.execute('SELECT * FROM cards WHERE active=1 ORDER BY is_default DESC,id LIMIT 1').fetchone();c.close()
        if not card:return await update.message.reply_text('❌ کارت پرداخت ثبت نشده است.')
        ctx.user_data.update(state='topup_receipt',topup_amount=a);return await update.message.reply_text(f'💳 مبلغ: {money(a)}\n\nکارت: {card["number"]}\n👤 {card["holder"]}\n\n📸 رسید را ارسال کن.')
    if st=='admin_card' and u['telegram_id']==OWNER_ID:
        p=t.split('|',1)
        if len(p)!=2:return await update.message.reply_text('❌ فرمت: شماره|نام')
        c=db();default=0 if c.execute('SELECT 1 FROM cards WHERE is_default=1').fetchone() else 1;c.execute('INSERT INTO cards(number,holder,active,is_default) VALUES(?,?,1,?)',(p[0].strip(),p[1].strip(),default));c.commit();c.close();ctx.user_data.clear();return await update.message.reply_text('✅ کارت ثبت شد.',reply_markup=kb([[('👑 پنل ادمین','admin')]]))
    if st=='admin_text' and u['telegram_id']==OWNER_ID:
        if '=' not in t:return await update.message.reply_text('❌ فرمت: کلید=متن')
        k,v=t.split('=',1);c=db();c.execute('INSERT INTO texts(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k.strip(),v));c.commit();c.close();return await update.message.reply_text('✅ متن ذخیره شد.')
    if st=='admin_product' and u['telegram_id']==OWNER_ID:
        try:k,p,d=t.split(':');p=int(p);d=int(d)
        except:return await update.message.reply_text('❌ فرمت: 1m:250000:30')
        c=db();c.execute('UPDATE products SET price=?,duration_days=? WHERE key=?',(p,d,k));c.commit();c.close();return await update.message.reply_text('✅ محصول بروزرسانی شد.')
    if st in ('chgadmin','transfer'):
        if not t.isdigit():return await update.message.reply_text('❌ فقط عدد ارسال کن.')
        bid=ctx.user_data['bid'];b=get_bot(bid,u['id']);c=db();c.execute('UPDATE bots SET admin_id=? WHERE id=?',(int(t),bid));c.commit();c.close();ctx.user_data.clear();return await update.message.reply_text('✅ انجام شد.',reply_markup=home(u['telegram_id']))
    if st=='chgtoken':
        ok,res=validate_token(t)
        if not ok:return await update.message.reply_text('❌ توکن معتبر نیست.')
        b=get_bot(ctx.user_data['bid'],u['id']);stop_instance(b['instance_path']);(Path(b['instance_path'])/'.env').write_text(f'BOT_TOKEN={t}\nOWNER_ID={b["admin_id"]}\nAPP_NAME=Eleven Store Dealer\n',encoding='utf8');start_instance(b['instance_path'],t,b['admin_id']);c=db();c.execute('UPDATE bots SET bot_token=?,bot_username=? WHERE id=?',(t,'@'+res.get('username',''),b['id']));c.commit();c.close();ctx.user_data.clear();return await update.message.reply_text('✅ توکن تغییر کرد و ربات دوباره اجرا شد.',reply_markup=home(u['telegram_id']))
    if st=='changeplan':
        if t not in PLANS:return await update.message.reply_text('❌ فقط 1m / 2m / 3m')
        n,p,_=PLANS[t];c=db();c.execute('UPDATE bots SET plan=?,plan_price=? WHERE id=?',(n,p,ctx.user_data['bid']));c.commit();c.close();ctx.user_data.clear();return await update.message.reply_text('✅ لایسنس تغییر کرد.',reply_markup=home(u['telegram_id']))
    if st=='renew':
        try:days=int(t)
        except:return await update.message.reply_text('❌ عدد روز را ارسال کن.')
        b=get_bot(ctx.user_data['bid'],u['id']);old=datetime.fromisoformat(b['expires_at']);base=max(now(),old);c=db();c.execute('UPDATE bots SET expires_at=?,status="active" WHERE id=?',((base+timedelta(days=days)).isoformat(),b['id']));c.commit();c.close();ctx.user_data.clear();return await update.message.reply_text('✅ ربات تمدید شد.',reply_markup=home(u['telegram_id']))
    if st=='delete':
        if t!='حذف':return await update.message.reply_text('❌ برای تأیید «حذف» را ارسال کن.')
        b=get_bot(ctx.user_data['bid'],u['id']);path=record_backup(b);stop_instance(b['instance_path']);shutil.rmtree(b['instance_path'],ignore_errors=True);c=db();c.execute('UPDATE bots SET status="deleted" WHERE id=?',(b['id'],));c.commit();c.close();ctx.user_data.clear()
        if path:await update.message.reply_document(open(path,'rb'),caption='💾 بکاپ نهایی قبل از حذف')
        return await update.message.reply_text('🗑 ربات حذف شد.',reply_markup=home(u['telegram_id']))
async def receipt(update,ctx):
    st=ctx.user_data.get('state');u=user(update.effective_user);fid=update.message.photo[-1].file_id if update.message.photo else (update.message.document.file_id if update.message.document else None)
    if st=='topup_receipt':
        if not fid:return await update.message.reply_text('❌ رسید باید عکس یا فایل باشد.')
        a=ctx.user_data['topup_amount'];c=db();c.execute('INSERT INTO orders(user_id,amount,card_amount,status,receipt_file_id,created_at) VALUES(?,?,?,?,?,?)',(u['id'],a,a,'wallet_topup_pending',fid,now().isoformat()));oid=c.lastrowid;c.commit();c.close();ctx.user_data.clear();await update.message.reply_text('✅ رسید ثبت شد و برای ادمین ارسال می‌شود.');await ctx.bot.send_message(OWNER_ID,f'💳 شارژ کیف پول\n👤 {u["telegram_id"]}\n💰 {money(a)}\n🧾 #{oid}',reply_markup=kb([[('🟢 تأیید',f'approve_topup:{oid}'),('🔴 رد',f'reject_topup:{oid}')]]));await ctx.bot.send_document(OWNER_ID,fid,caption=f'رسید #{oid}');return
    if st=='awaiting_receipt':
        if not fid:return await update.message.reply_text('❌ رسید باید عکس یا فایل باشد.')
        oid=ctx.user_data['order_id'];c=db();c.execute('UPDATE orders SET receipt_file_id=? WHERE id=?',(fid,oid));o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone();c.commit();c.close();await update.message.reply_text('✅ رسید دریافت شد و منتظر تأیید ادمین است.')
        try:
            await ctx.bot.send_message(OWNER_ID,f'💳 سفارش لایسنس #{oid}\n👤 User ID: {u["telegram_id"]}\n💰 کل: {money(o["amount"])}\n💰 کیف پول: {money(o["wallet_amount"])}\n📌 کارت: {money(o["card_amount"])}',reply_markup=kb([[('🟢 تأیید سفارش',f'approve_order:{oid}'),('🔴 رد سفارش',f'reject_order:{oid}')]]))
            await ctx.bot.send_document(OWNER_ID,fid,caption=f'رسید سفارش لایسنس #{oid}')
        except Exception:pass
        return
    if st=='import':
        doc=update.message.document
        if not doc or not doc.file_name.lower().endswith('.sql'):return await update.message.reply_text('❌ فقط فایل SQL ارسال کن.')
        b=get_bot(ctx.user_data['bid'],u['id']);tmp=Path(tempfile.mktemp(suffix='.sql'));f=await doc.get_file();await f.download_to_drive(str(tmp));target=Path(b['instance_path'])/'database'/'app.db';stop_instance(b['instance_path'])
        try:new=Path(tempfile.mktemp(suffix='.db'));s=sqlite3.connect(new);s.executescript(tmp.read_text(encoding='utf8'));s.close();shutil.copy2(new,target);new.unlink();start_instance(b['instance_path'],b['bot_token'],b['admin_id']);await update.message.reply_text('✅ بکاپ وارد و ربات دوباره اجرا شد.',reply_markup=home(u['telegram_id']))
        except Exception as e:await update.message.reply_text('❌ Import ناموفق: '+str(e)[:300])
        finally:
            try:tmp.unlink()
            except:pass
async def provision_cb(update,ctx):
    q=update.callback_query;await q.answer();u=user(q.from_user);k=ctx.user_data.get('plan_key');token=ctx.user_data.get('bot_token');aid=ctx.user_data.get('admin_id',u['telegram_id'])
    if not k or not token:return await q.edit_message_text('❌ اطلاعات ناقص است.')
    n,price,_=PLANS[k];c=db();balance=c.execute('SELECT balance FROM users WHERE id=?',(u['id'],)).fetchone()['balance'];card=c.execute('SELECT * FROM cards WHERE active=1 ORDER BY is_default DESC,id LIMIT 1').fetchone();c.close();wallet=min(balance,price);short=price-wallet
    if short:
        if wallet:change_balance(u['id'],-wallet,'hold','رزرو کیف پول')
        c=db();c.execute('INSERT INTO orders(user_id,plan_key,token,admin_id,amount,wallet_amount,card_amount,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(u['id'],k,token,aid,price,wallet,short,'awaiting_receipt',now().isoformat()));oid=c.lastrowid;c.commit();c.close();ctx.user_data={'state':'awaiting_receipt','order_id':oid,'plan_key':k,'bot_token':token,'admin_id':aid}
        if not card:
            if wallet:change_balance(u['id'],wallet,'refund','برگشت رزرو')
            return await q.edit_message_text('❌ کارت پرداخت ثبت نشده است.')
        return await q.edit_message_text(f'💳 قیمت: {money(price)}\n💰 کیف پول: {money(wallet)}\n📌 مبلغ قابل پرداخت: {money(short)}\n\n💳 کارت:\n{card["number"]}\n👤 {card["holder"]}\n\n📸 رسید را ارسال کن.')
    try:bid=provision(u['id'],aid,token,k);change_balance(u['id'],-price,'purchase','خرید لایسنس');ctx.user_data.clear();return await q.edit_message_text('🎉 ربات با موفقیت ساخته و راه‌اندازی شد!',reply_markup=kb([[('⚙️ مدیریت ربات','manage'),('🔙 بازگشت','back')]]))
    except Exception as e:return await q.edit_message_text('❌ ساخت ربات ناموفق بود.\n\n'+str(e)[:700])
async def payment_admin_cb(update,ctx):
    q=update.callback_query;await q.answer();d=q.data;oid=int(d.split(':')[1]);c=db();o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone();c.close()
    if not o:return
    if d.startswith('reject_topup'):c=db();c.execute('UPDATE orders SET status="rejected",rejected_at=? WHERE id=?',(now().isoformat(),oid));c.commit();c.close();return await q.edit_message_text(f'🔴 شارژ #{oid} رد شد.')
    if d.startswith('approve_topup'):
        if o['status']=='paid':return await q.edit_message_text('⚠️ قبلاً پردازش شده.')
        change_balance(o['user_id'],o['amount'],'topup','شارژ کیف پول',oid);c=db();c.execute('UPDATE orders SET status="paid",approved_at=? WHERE id=?',(now().isoformat(),oid));tid=c.execute('SELECT telegram_id FROM users WHERE id=?',(o['user_id'],)).fetchone()['telegram_id'];c.commit();c.close();await q.edit_message_text(f'🟢 شارژ #{oid} تأیید شد.');await ctx.bot.send_message(tid,f'🟢 شارژ کیف پول شما به مبلغ {money(o["amount"])} تأیید شد.');return
    if d.startswith('reject_order'):
        if o['wallet_amount']:change_balance(o['user_id'],o['wallet_amount'],'refund','بازگشت رزرو سفارش',oid)
        c=db();c.execute('UPDATE orders SET status="rejected",rejected_at=? WHERE id=?',(now().isoformat(),oid));tid=c.execute('SELECT telegram_id FROM users WHERE id=?',(o['user_id'],)).fetchone()['telegram_id'];c.commit();c.close();await q.edit_message_text(f'🔴 سفارش #{oid} رد شد.');await ctx.bot.send_message(tid,'🔴 سفارش شما رد شد و مبلغ رزرو شده کیف پول برگشت داده شد.');return
    if d.startswith('approve_order'):
        if o['status']!='awaiting_receipt':return await q.edit_message_text('⚠️ سفارش قبلاً پردازش شده است.')
        try:
            bid=provision(o['user_id'],o['admin_id'],o['token'],o['plan_key'])
            if o['wallet_amount']:change_balance(o['user_id'],0,'order','رزرو قبلی در سفارش',oid)
            c=db();c.execute('UPDATE orders SET bot_id=?,status="paid",approved_at=? WHERE id=?',(bid,now().isoformat(),oid));tid=c.execute('SELECT telegram_id FROM users WHERE id=?',(o['user_id'],)).fetchone()['telegram_id'];c.commit();c.close();await q.edit_message_text(f'🟢 سفارش #{oid} تأیید و ربات ساخته شد.');await ctx.bot.send_message(tid,'🎉 پرداخت تأیید شد و ربات شما ساخته و راه‌اندازی شد.')
        except Exception as e:await q.edit_message_text('❌ ساخت ربات بعد از تأیید ناموفق بود: '+str(e)[:500])
        return
async def expiry_job(ctx):
    c=db();rows=c.execute('SELECT * FROM bots WHERE status="active" AND expires_at<=?',(now().isoformat(),)).fetchall();c.close()
    for b in rows:
        path=record_backup(b);stop_instance(b['instance_path']);c=db();c.execute('UPDATE bots SET status="expired" WHERE id=?',(b['id'],));tid=c.execute('SELECT telegram_id FROM users WHERE id=?',(b['user_id'],)).fetchone()['telegram_id'];c.commit();c.close()
        if path:
            try:await ctx.bot.send_document(tid,open(path,'rb'),caption='💾 لایسنس منقضی شد؛ بکاپ SQL شما پیوست است.')
            except:pass
def main():
    if not BOT_TOKEN:raise RuntimeError('BOT_TOKEN در .env تنظیم نشده است.')
    init_db();app=Application.builder().token(BOT_TOKEN).build();app.add_handler(CommandHandler('start',start));app.add_handler(CallbackQueryHandler(provision_cb,pattern='^provision$'));app.add_handler(CallbackQueryHandler(payment_admin_cb,pattern='^(approve_topup|reject_topup|approve_order|reject_order):'));app.add_handler(CallbackQueryHandler(cb));app.add_handler(MessageHandler(filters.PHOTO|filters.Document.ALL,receipt));app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,text));app.job_queue.run_repeating(expiry_job,60,10);print('Eleven Store starting...');app.run_polling(drop_pending_updates=True)
if __name__=='__main__':main()
