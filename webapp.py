import hashlib, hmac, json, os, time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import BOT_TOKEN, APP_NAME
from database.core import get_connection

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / 'miniapp'
app = FastAPI(title=f'{APP_NAME} Mini App API', version='1.0.0')


def validate_init_data(init_data: str, max_age: int = 86400):
    if not init_data or not BOT_TOKEN:
        raise HTTPException(401, 'Telegram session is missing')
    pairs = {}
    for item in init_data.split('&'):
        if '=' in item:
            k, v = item.split('=', 1)
            from urllib.parse import unquote
            pairs[k] = unquote(v)
    received = pairs.pop('hash', None)
    if not received:
        raise HTTPException(401, 'Invalid Telegram session')
    auth_date = int(pairs.get('auth_date', '0') or 0)
    if not auth_date or time.time() - auth_date > max_age:
        raise HTTPException(401, 'Telegram session expired')
    data_check = '\n'.join(f'{k}={pairs[k]}' for k in sorted(pairs))
    secret = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise HTTPException(401, 'Invalid Telegram signature')
    user = json.loads(pairs.get('user', '{}'))
    if not user.get('id'):
        raise HTTPException(401, 'Telegram user not found')
    return user


def user_from_header(x_telegram_init_data: Optional[str]):
    return validate_init_data(x_telegram_init_data or '')


def money(n):
    return f'{int(n):,} تومان'


class Preview(BaseModel):
    panel_id: int
    product_id: Optional[int] = None
    kind: str = 'suggested'
    custom_gb: int = 0
    custom_days: int = 0
    custom_users: int = 0
    coupon: Optional[str] = None


@app.get('/api/health')
def health():
    return {'ok': True, 'app': APP_NAME}


@app.get('/api/me')
def me(x_telegram_init_data: Optional[str] = Header(default=None)):
    u = user_from_header(x_telegram_init_data)
    c = get_connection()
    row = c.execute('SELECT id,telegram_id,username,first_name,balance,created_at FROM users WHERE telegram_id=?', (u['id'],)).fetchone()
    if not row:
        c.execute('INSERT INTO users(telegram_id,username,first_name) VALUES(?,?,?)', (u['id'], u.get('username'), u.get('first_name')))
        c.commit()
        row = c.execute('SELECT id,telegram_id,username,first_name,balance,created_at FROM users WHERE telegram_id=?', (u['id'],)).fetchone()
    services = c.execute('SELECT COUNT(*) FROM services WHERE user_id=?', (row['id'],)).fetchone()[0]
    orders = c.execute('SELECT COUNT(*) FROM orders WHERE user_id=?', (row['id'],)).fetchone()[0]
    c.close()
    return {'user': dict(row), 'stats': {'services': services, 'orders': orders}}


@app.get('/api/panels')
def panels(x_telegram_init_data: Optional[str] = Header(default=None)):
    user_from_header(x_telegram_init_data)
    c = get_connection()
    rows = c.execute("SELECT id,name,url,status FROM panels WHERE status!='disabled' ORDER BY id DESC").fetchall()
    c.close()
    return {'items': [dict(r) for r in rows]}


@app.get('/api/products')
def products(x_telegram_init_data: Optional[str] = Header(default=None)):
    user_from_header(x_telegram_init_data)
    c = get_connection()
    rows = c.execute('SELECT id,name,kind,data_gb,days,max_users,price,description,capacity,enabled FROM products WHERE enabled=1 ORDER BY id DESC').fetchall()
    c.close()
    return {'items': [dict(r) for r in rows]}


@app.get('/api/custom-settings')
def custom_settings(x_telegram_init_data: Optional[str] = Header(default=None)):
    user_from_header(x_telegram_init_data)
    c = get_connection(); r = c.execute('SELECT * FROM custom_settings WHERE id=1').fetchone(); c.close()
    return {'settings': dict(r) if r else {}}


@app.get('/api/services')
def services(x_telegram_init_data: Optional[str] = Header(default=None)):
    u = user_from_header(x_telegram_init_data)
    c = get_connection()
    usr = c.execute('SELECT id FROM users WHERE telegram_id=?', (u['id'],)).fetchone()
    if not usr:
        c.close(); return {'items': []}
    rows = c.execute('''SELECT s.id,s.username,s.password,s.status,s.data_limit_bytes,s.started_at,s.expires_at,
                       p.name panel_name,p.url panel_url
                       FROM services s JOIN panels p ON p.id=s.panel_id
                       WHERE s.user_id=? ORDER BY s.id DESC''', (usr['id'],)).fetchall()
    c.close()
    items=[]
    for r in rows:
        x=dict(r); x['panel_url']=x['panel_url'].rstrip('/') + '/dashboard'; items.append(x)
    return {'items': items}


@app.get('/api/transactions')
def transactions(x_telegram_init_data: Optional[str] = Header(default=None)):
    u = user_from_header(x_telegram_init_data)
    c = get_connection(); usr=c.execute('SELECT id FROM users WHERE telegram_id=?',(u['id'],)).fetchone()
    if not usr: c.close(); return {'items': []}
    rows=c.execute('SELECT id,amount,type,description,order_id,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 50',(usr['id'],)).fetchall(); c.close()
    return {'items':[dict(r) for r in rows]}


@app.get('/api/support')
def support(x_telegram_init_data: Optional[str] = Header(default=None)):
    user_from_header(x_telegram_init_data)
    c=get_connection(); vals={r['key']:r['value'] for r in c.execute("SELECT key,value FROM settings WHERE key IN ('support_text','support_username','support_link','bot_name')")}; c.close()
    return {'text': vals.get('support_text',''), 'username': vals.get('support_username',''), 'link': vals.get('support_link',''), 'bot_name': vals.get('bot_name') or APP_NAME}


@app.post('/api/orders/preview')
def order_preview(payload: Preview, x_telegram_init_data: Optional[str] = Header(default=None)):
    u=user_from_header(x_telegram_init_data)
    c=get_connection(); panel=c.execute('SELECT id,name FROM panels WHERE id=?',(payload.panel_id,)).fetchone()
    if not panel: c.close(); raise HTTPException(404,'Panel not found')
    total=0; product=None
    if payload.kind=='suggested':
        product=c.execute('SELECT * FROM products WHERE id=? AND enabled=1',(payload.product_id,)).fetchone()
        if not product: c.close(); raise HTTPException(404,'Plan not found')
        total=int(product['price'])
    else:
        s=c.execute('SELECT * FROM custom_settings WHERE id=1').fetchone()
        if not s or not s['enabled']: c.close(); raise HTTPException(400,'Custom plan is disabled')
        if payload.custom_gb==0:
            if payload.custom_days<=0: c.close(); raise HTTPException(400,'Months must be greater than zero')
            total=payload.custom_days*int(s['price_per_month'])
        else:
            if payload.custom_gb<int(s['min_gb']) or (s['max_gb'] and payload.custom_gb>int(s['max_gb'])): c.close(); raise HTTPException(400,'Volume is outside allowed range')
            if payload.custom_days<=0: c.close(); raise HTTPException(400,'Duration must be greater than zero')
            total=payload.custom_gb*int(s['price_per_gb']) + payload.custom_days*int(s['price_per_day'])
    usr=c.execute('SELECT balance FROM users WHERE telegram_id=?',(u['id'],)).fetchone(); balance=int(usr['balance']) if usr else 0
    c.close()
    return {'panel':dict(panel),'product':dict(product) if product else None,'total':total,'total_text':money(total),'wallet_balance':balance,'wallet_cover':balance>=total,'card_needed':max(0,total-balance)}


@app.get('/api/bootstrap')
def bootstrap(x_telegram_init_data: Optional[str] = Header(default=None)):
    user_from_header(x_telegram_init_data)
    return {'app':APP_NAME,'api_version':'1.0','features':['services','wallet','purchase','support']}


app.mount('/assets', StaticFiles(directory=str(WEB_DIR)), name='assets')

@app.get('/')
def index():
    return FileResponse(WEB_DIR/'index.html')
