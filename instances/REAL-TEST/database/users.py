from .core import get_connection
def upsert_user(tid,username,first_name):
 c=get_connection(); c.execute('INSERT INTO users(telegram_id,username,first_name) VALUES(?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name',(tid,username,first_name)); c.commit(); r=c.execute('SELECT * FROM users WHERE telegram_id=?',(tid,)).fetchone(); c.close(); return dict(r)
def get_user_by_tid(tid):
 c=get_connection(); r=c.execute('SELECT * FROM users WHERE telegram_id=?',(tid,)).fetchone(); c.close(); return dict(r) if r else None
def get_user(uid):
 c=get_connection(); r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return dict(r) if r else None
def set_balance(uid,delta,typ='adjustment',desc='',order_id=None):
 c=get_connection(); c.execute('UPDATE users SET balance=balance+? WHERE id=?',(delta,uid)); c.execute('INSERT INTO transactions(user_id,amount,type,description,order_id) VALUES(?,?,?,?,?)',(uid,delta,typ,desc,order_id)); c.commit(); r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return dict(r)
def list_users(mode='all',q=None):
 c=get_connection(); params=[]; where=''
 if q: where=' WHERE (u.username LIKE ? OR CAST(u.telegram_id AS TEXT) LIKE ? OR u.first_name LIKE ?)'; params=[f'%{q}%',f'%{q}%',f'%{q}%']
 if mode=='buyers': where += (' AND ' if where else ' WHERE ')+'EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status="completed")'
 if mode=='nonbuyers': where += (' AND ' if where else ' WHERE ')+'NOT EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status="completed")'
 if mode=='balance': where += (' AND ' if where else ' WHERE ')+'u.balance>0'
 rows=c.execute('SELECT u.* FROM users u'+where+' ORDER BY u.id DESC LIMIT 100',params).fetchall(); c.close(); return [dict(x) for x in rows]


def is_blocked(uid):
 c=get_connection(); r=c.execute('SELECT blocked FROM user_controls WHERE user_id=?',(uid,)).fetchone(); c.close(); return bool(r[0]) if r else False

def set_blocked(uid,blocked):
 c=get_connection(); c.execute('INSERT INTO user_controls(user_id,blocked) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET blocked=excluded.blocked',(uid,int(blocked))); c.commit(); c.close(); return bool(blocked)

def approve_topup(topup_id, admin_id):
 c=get_connection();
 try:
  c.execute('BEGIN IMMEDIATE')
  r=c.execute("SELECT user_id,amount,status FROM wallet_topups WHERE id=?",(topup_id,)).fetchone()
  if not r or r['status']!='pending_review': c.rollback(); return None
  c.execute('UPDATE users SET balance=balance+? WHERE id=?',(r['amount'],r['user_id']))
  c.execute("INSERT INTO transactions(user_id,amount,type,description) VALUES(?,?,?,?)",(r['user_id'],r['amount'],'wallet_topup','شارژ کیف پول'))
  c.execute("UPDATE wallet_topups SET status='completed',approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending_review'",(admin_id,topup_id))
  c.commit(); return {'user_id':r['user_id'],'amount':r['amount']}
 except Exception:
  c.rollback(); raise
 finally: c.close()

def reject_topup(topup_id, admin_id):
 c=get_connection();
 try:
  c.execute('BEGIN IMMEDIATE')
  r=c.execute("SELECT user_id,amount,status FROM wallet_topups WHERE id=?",(topup_id,)).fetchone()
  if not r or r['status']!='pending_review': c.rollback(); return None
  c.execute("UPDATE wallet_topups SET status='rejected',rejected_by=?,rejected_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending_review'",(admin_id,topup_id))
  c.commit(); return {'user_id':r['user_id'],'amount':r['amount']}
 except Exception:
  c.rollback(); raise
 finally: c.close()
