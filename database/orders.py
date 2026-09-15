from .core import get_connection
def create_order(**kw):
 c=get_connection(); keys=','.join(kw); qs=','.join('?' for _ in kw); cur=c.execute(f'INSERT INTO orders({keys}) VALUES({qs})',list(kw.values())); c.commit(); r=dict(c.execute('SELECT * FROM orders WHERE id=?',(cur.lastrowid,)).fetchone()); c.close(); return r
def get_order(oid):
 c=get_connection(); x=c.execute('SELECT o.*,u.telegram_id,u.username AS telegram_username,u.first_name,p.name product_name,pa.name panel_name FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN products p ON p.id=o.product_id JOIN panels pa ON pa.id=o.panel_id WHERE o.id=?',(oid,)).fetchone(); c.close(); return dict(x) if x else None
def set_order(oid,**kw):
 if not kw:return
 c=get_connection(); sets=','.join(f'{k}=?' for k in kw); c.execute(f'UPDATE orders SET {sets} WHERE id=?',list(kw.values())+[oid]); c.commit(); c.close()
def list_pending():
 c=get_connection(); r=[dict(x) for x in c.execute('SELECT o.*,u.telegram_id,u.username AS telegram_username,u.first_name,p.name product_name,pa.name panel_name FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN products p ON p.id=o.product_id JOIN panels pa ON pa.id=o.panel_id WHERE o.status IN ("awaiting_receipt","pending_review") ORDER BY o.id ASC')]; c.close(); return r


def claim_for_processing(oid, approved_by=0):
 c=get_connection(); cur=c.execute("UPDATE orders SET status='provisioning',approved_by=?,approved_at=? WHERE id=? AND status IN ('paid','pending_review')",(approved_by or None,__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),oid)); c.commit(); ok=cur.rowcount==1; c.close(); return ok
