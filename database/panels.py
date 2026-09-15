from .core import get_connection
def add_panel(name,url,username,password):
 c=get_connection(); cur=c.execute('INSERT INTO panels(name,url,username,password) VALUES(?,?,?,?)',(name,url,username,password)); c.commit(); r=c.execute('SELECT * FROM panels WHERE id=?',(cur.lastrowid,)).fetchone(); c.close(); return dict(r)
def get_panels():
 c=get_connection(); r=[dict(x) for x in c.execute('SELECT * FROM panels ORDER BY id DESC')]; c.close(); return r
def get_panel(pid):
 c=get_connection(); x=c.execute('SELECT * FROM panels WHERE id=?',(pid,)).fetchone(); c.close(); return dict(x) if x else None
def update_panel(pid,status=None,token=None):
 c=get_connection(); c.execute('UPDATE panels SET status=COALESCE(?,status),access_token=COALESCE(?,access_token) WHERE id=?',(status,token,pid)); c.commit(); c.close()
def delete_panel(pid):
 c=get_connection(); c.execute('DELETE FROM panels WHERE id=?',(pid,)); c.commit(); c.close()
