from .core import get_connection
def create_product(name,data_gb,days,max_users,price,description,capacity=0):
 c=get_connection(); cur=c.execute('INSERT INTO products(name,kind,data_gb,days,max_users,price,description,capacity) VALUES(?,?,?,?,?,?,?,?)',(name,'suggested',data_gb,days,max_users,price,description,capacity)); c.commit(); r=dict(c.execute('SELECT * FROM products WHERE id=?',(cur.lastrowid,)).fetchone()); c.close(); return r
def list_products(active_only=False):
 c=get_connection(); q='SELECT * FROM products';
 if active_only:q+=' WHERE enabled=1 AND (capacity=0 OR sold<capacity)'
 q+=' ORDER BY id DESC'; r=[dict(x) for x in c.execute(q)]; c.close(); return r
def get_product(pid):
 c=get_connection(); x=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone(); c.close(); return dict(x) if x else None
def toggle_product(pid):
 c=get_connection(); c.execute('UPDATE products SET enabled=1-enabled WHERE id=?',(pid,)); c.commit(); c.close()
def update_product(pid,**kw):
 allowed={'name','data_gb','days','max_users','price','description','capacity','kind','enabled'}
 kw={k:v for k,v in kw.items() if k in allowed}
 if not kw: return get_product(pid)
 c=get_connection(); c.execute('UPDATE products SET '+','.join(f'{k}=?' for k in kw)+' WHERE id=?',list(kw.values())+[pid]); c.commit()
 r=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone(); c.close(); return dict(r) if r else None
def delete_product(pid):
 c=get_connection(); c.execute('DELETE FROM products WHERE id=?',(pid,)); c.commit(); c.close()
def reserve_product(pid):
 c=get_connection(); cur=c.execute('UPDATE products SET sold=sold+1 WHERE id=? AND enabled=1 AND (capacity=0 OR sold<capacity)',(pid,)); c.commit(); ok=cur.rowcount>0; c.close(); return ok
def get_custom():
 c=get_connection(); x=c.execute('SELECT * FROM custom_settings WHERE id=1').fetchone(); c.close(); return dict(x)
def save_custom(**kw):
 c=get_connection();
 if kw:
  allowed={'enabled','min_gb','max_gb','price_per_gb','min_days','max_days','price_per_month','price_per_day','price_limited_unlimited','ask_duration','default_days','users_enabled','min_users','max_users','price_per_user'}; kw={k:v for k,v in kw.items() if k in allowed};
  if kw:c.execute('UPDATE custom_settings SET '+','.join(f'{k}=?' for k in kw)+' WHERE id=1',list(kw.values())); c.commit()
 x=dict(c.execute('SELECT * FROM custom_settings WHERE id=1').fetchone()); c.close(); return x
def custom_price(gb,days,users=0):
 s=get_custom()
 if not s['enabled']: raise ValueError('پلن دلخواه غیرفعال است.')
 if gb==0 and days==0:
  monthly=int(s.get('price_per_month',0) or 0)
  if monthly<=0: raise ValueError('برای حجم و مدت نامحدود، قیمت ماهانه باید توسط ادمین تنظیم شود.')
  return monthly,s
 if gb and days==0:
  unlimited=int(s.get('price_limited_unlimited',0) or 0)
  if gb<s['min_gb'] or (s['max_gb'] and gb>s['max_gb']): raise ValueError('حجم خارج از محدوده است.')
  # Optional override; otherwise the per-GB price is used for limited-volume/unlimited-duration.
  return (unlimited if unlimited>0 else gb*int(s.get('price_per_gb',0) or 0)),s
 if gb and gb<s['min_gb']: raise ValueError(f'حداقل حجم {s["min_gb"]} گیگ است.')
 if s['max_gb'] and gb>s['max_gb']: raise ValueError(f'حداکثر حجم {s["max_gb"]} گیگ است.')
 if days and days<s['min_days']: raise ValueError(f'حداقل زمان {s["min_days"]} روز است.')
 if s['max_days'] and days>s['max_days']: raise ValueError(f'حداکثر زمان {s["max_days"]} روز است.')
 if gb==0:
  if days<=0: raise ValueError('مدت نامعتبر است.')
  if days % 30 != 0: raise ValueError('برای حجم نامحدود، مدت باید بر اساس ماه انتخاب شود.')
  months=days//30
  monthly=int(s.get('price_per_month',0) or 0)
  if monthly<=0: raise ValueError('قیمت ماهانه سرویس حجم نامحدود توسط ادمین تنظیم نشده است.')
  price=months*monthly
 elif days==0:
  raise ValueError('برای حجم محدود، مدت باید مشخص باشد.')
 else:
  price=gb*s['price_per_gb']+days*s['price_per_day']
 return price,s


def release_product(pid):
 if not pid:return
 c=get_connection(); c.execute('UPDATE products SET sold=CASE WHEN sold>0 THEN sold-1 ELSE 0 END WHERE id=?',(pid,)); c.commit(); c.close()
