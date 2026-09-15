from pathlib import Path
from getpass import getpass
root=Path(__file__).resolve().parent
token=getpass("BOT_TOKEN: ").strip()
owner=input("OWNER_ID: ").strip()
(root/".env").write_text(f"BOT_TOKEN={token}\nOWNER_ID={owner}\nAPP_NAME=Eleven Store\nLOG_LEVEL=INFO\n",encoding="utf-8")
print(".env created")
