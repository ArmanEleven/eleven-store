from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip()
OWNER_ID=int(os.getenv('OWNER_ID','0') or 0)
APP_NAME=os.getenv('APP_NAME','Eleven Store').strip() or 'Eleven Store'
LOG_LEVEL=os.getenv('LOG_LEVEL','INFO').strip().upper() or 'INFO'


# Whether to verify TLS certificates when calling a PasarGuard panel's API.
# Most self-hosted panels use self-signed certs, so this defaults to False —
# but set it to "1" in .env once your panels sit behind a real certificate,
# since leaving it off exposes you to MITM attacks on panel credentials.
PANEL_VERIFY_SSL=os.getenv('PANEL_VERIFY_SSL','0').strip() in ('1','true','True','on','yes')
