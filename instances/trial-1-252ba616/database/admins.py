from .core import get_connection
def add_admin(tid,role='admin'):
 c=get_connection(); c.execute('INSERT OR IGNORE INTO admins(telegram_id,role) VALUES(?,?)',(tid,role)); c.commit(); c.close()
def is_admin(tid):
 c=get_connection(); x=c.execute('SELECT 1 FROM admins WHERE telegram_id=? AND is_active=1',(tid,)).fetchone(); c.close(); return bool(x)
def list_admin_ids():
 c=get_connection(); r=[x[0] for x in c.execute('SELECT telegram_id FROM admins WHERE is_active=1')]; c.close(); return r
