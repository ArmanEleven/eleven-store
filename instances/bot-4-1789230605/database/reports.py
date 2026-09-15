import json
from .core import get_connection
TOPICS=['users','purchases','payments','panels','wallet','products','admins','errors','system']
def get_config():
 c=get_connection(); r=c.execute('SELECT * FROM reports_config WHERE id=1').fetchone(); c.close(); return dict(r)
def save(chat_id,topics):
 c=get_connection(); c.execute('UPDATE reports_config SET chat_id=?,enabled=1,topics_json=? WHERE id=1',(chat_id,json.dumps(topics))); c.commit(); c.close()
def topics():
 c=get_connection(); r=c.execute('SELECT topics_json FROM reports_config WHERE id=1').fetchone(); c.close(); return json.loads(r[0] or '{}')


def clear_config():
 c=get_connection(); c.execute("UPDATE reports_config SET chat_id=NULL,enabled=0,topics_json='{}' WHERE id=1"); c.commit(); c.close()
