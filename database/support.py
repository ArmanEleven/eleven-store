from .core import get_connection

def get_open_ticket(user_id):
    c=get_connection()
    r=c.execute("SELECT * FROM support_tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",(user_id,)).fetchone()
    c.close(); return dict(r) if r else None

def create_ticket(user_id):
    c=get_connection()
    cur=c.execute("INSERT INTO support_tickets(user_id,status,last_message_at) VALUES(?,'open',CURRENT_TIMESTAMP)",(user_id,))
    c.commit(); tid=cur.lastrowid
    r=c.execute('SELECT * FROM support_tickets WHERE id=?',(tid,)).fetchone(); c.close(); return dict(r)

def get_ticket(tid):
    c=get_connection(); r=c.execute('SELECT * FROM support_tickets WHERE id=?',(tid,)).fetchone(); c.close()
    return dict(r) if r else None

def close_ticket(tid):
    c=get_connection(); c.execute("UPDATE support_tickets SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); c.commit(); c.close()

def add_message(tid,sender,text,telegram_message_id=None,admin_message_id=None):
    c=get_connection()
    c.execute('INSERT INTO support_messages(ticket_id,sender,text,telegram_message_id,admin_message_id) VALUES(?,?,?,?,?)',(tid,sender,text,telegram_message_id,admin_message_id))
    c.execute('UPDATE support_tickets SET last_message_at=CURRENT_TIMESTAMP WHERE id=?',(tid,))
    c.commit(); c.close()

def list_messages(tid):
    c=get_connection()
    r=[dict(x) for x in c.execute('SELECT * FROM support_messages WHERE ticket_id=? ORDER BY id ASC',(tid,))]
    c.close(); return r

def list_open_tickets(limit=30):
    c=get_connection()
    r=[dict(x) for x in c.execute("SELECT * FROM support_tickets WHERE status='open' ORDER BY last_message_at DESC LIMIT ?",(limit,))]
    c.close(); return r
