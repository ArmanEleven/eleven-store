from .core import get_connection
from datetime import datetime,timezone,timedelta
def add_method(card,holder,auto=False,minutes=5):
 c=get_connection(); cur=c.execute('INSERT INTO payment_methods(name,kind,card_number,card_holder,auto_approve,auto_approve_minutes,enabled) VALUES(?,?,?,?,?,?,1)',('کارت به کارت','card_to_card',card,holder,int(auto),int(minutes))); c.commit(); r=dict(c.execute('SELECT * FROM payment_methods WHERE id=?',(cur.lastrowid,)).fetchone()); c.close(); return r

def set_default_method(mid):
 c=get_connection(); c.execute('UPDATE payment_methods SET enabled=0'); c.execute('UPDATE payment_methods SET enabled=1 WHERE id=?',(mid,)); c.commit(); c.close()
def get_method():
 c=get_connection(); x=c.execute('SELECT * FROM payment_methods WHERE enabled=1 ORDER BY id DESC LIMIT 1').fetchone(); c.close(); return dict(x) if x else None
def list_methods():
 c=get_connection(); r=[dict(x) for x in c.execute('SELECT * FROM payment_methods ORDER BY id DESC')]; c.close(); return r
def create_coupon(code,kind,value,max_users,max_uses_per_user,expiry_days):
 expires=None if expiry_days==0 else (datetime.now(timezone.utc)+timedelta(days=expiry_days)).isoformat(); c=get_connection(); cur=c.execute('INSERT INTO coupons(code,kind,value,max_users,max_uses_per_user,expires_at) VALUES(?,?,?,?,?,?)',(code.upper(),kind,value,max_users,max_uses_per_user,expires)); c.commit(); r=dict(c.execute('SELECT * FROM coupons WHERE id=?',(cur.lastrowid,)).fetchone()); c.close(); return r
def list_coupons():
 c=get_connection(); r=[dict(x) for x in c.execute('SELECT * FROM coupons ORDER BY id DESC')]; c.close(); return r


def get_coupon(code):
 c=get_connection(); x=c.execute("SELECT * FROM coupons WHERE UPPER(code)=UPPER(?) AND enabled=1",(code.strip(),)).fetchone(); c.close(); return dict(x) if x else None

def coupon_usage_count(code):
 c=get_connection(); x=c.execute('SELECT COUNT(*) FROM coupon_usages WHERE UPPER(code)=UPPER(?)',(code,)).fetchone(); c.close(); return int(x[0])

def user_coupon_usage(code,user_id):
 c=get_connection(); x=c.execute('SELECT COUNT(*) FROM coupon_usages WHERE UPPER(code)=UPPER(?) AND user_id=?',(code,user_id)).fetchone(); c.close(); return int(x[0])

def coupon_available(code,user_id):
 c=get_connection(); row=c.execute('SELECT * FROM coupons WHERE UPPER(code)=UPPER(?) AND enabled=1',(code.strip(),)).fetchone()
 if not row: c.close(); return False,'کد تخفیف پیدا نشد.'
 r=dict(row); now=datetime.now(timezone.utc)
 if r.get('expires_at'):
  try:
   if datetime.fromisoformat(r['expires_at']) < now: c.close(); return False,'کد تخفیف منقضی شده است.'
  except Exception: pass
 total=c.execute("SELECT COUNT(*) FROM coupon_usages WHERE UPPER(code)=UPPER(?) AND status IN ('pending','used')",(code,)).fetchone()[0]
 mine=c.execute("SELECT COUNT(*) FROM coupon_usages WHERE UPPER(code)=UPPER(?) AND user_id=? AND status IN ('pending','used')",(code,user_id)).fetchone()[0]
 c.close()
 if r['max_users'] and total>=r['max_users']: return False,'ظرفیت استفاده از این کد تکمیل شده است.'
 if r['max_uses_per_user'] and mine>=r['max_uses_per_user']: return False,'شما قبلاً به سقف استفاده از این کد رسیده‌اید.'
 return True,r

def reserve_coupon(code,user_id,order_id):
 ok,info=coupon_available(code,user_id)
 if not ok: raise ValueError(info)
 c=get_connection(); c.execute("INSERT INTO coupon_usages(code,user_id,order_id,status) VALUES(?,?,?,'pending')",(code.upper(),user_id,order_id)); c.commit(); c.close()

def finalize_coupon(order_id,used=True):
 c=get_connection(); c.execute("UPDATE coupon_usages SET status=? WHERE order_id=? AND status='pending'",('used' if used else 'cancelled',order_id)); c.commit(); c.close()

def redeem_coupon(code,user_id,order_id=None):
 c=get_connection(); c.execute("INSERT INTO coupon_usages(code,user_id,order_id,status) VALUES(?,?,?,?)",(code.upper(),user_id,order_id,'used')); c.commit(); c.close()
