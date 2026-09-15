from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip()
OWNER_ID=int(os.getenv('OWNER_ID','0') or 0)
APP_NAME=os.getenv('APP_NAME','PasarGuard Dealer').strip() or 'PasarGuard Dealer'
LOG_LEVEL=os.getenv('LOG_LEVEL','INFO').strip().upper() or 'INFO'
