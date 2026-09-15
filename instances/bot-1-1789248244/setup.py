from pathlib import Path

root=Path(__file__).resolve().parent
p=root/'.env'
if p.exists():
    print('.env already exists. Nothing changed.')
    raise SystemExit(0)
print('=== PasarGuard Dealer Bot setup ===')
token=input('Telegram Bot Token: ').strip()
while not token:
    token=input('Telegram Bot Token cannot be empty: ').strip()
owner=input('Owner Telegram ID: ').strip()
while not owner.isdigit() or int(owner)<=0:
    owner=input('Owner Telegram ID must be numeric: ').strip()
name=input('Bot name [PasarGuard Dealer]: ').strip() or 'PasarGuard Dealer'
p.write_text(f'BOT_TOKEN={token}\nOWNER_ID={owner}\nAPP_NAME={name}\nLOG_LEVEL=INFO\n', encoding='utf-8')
print('\n.env created successfully.')
print('Now run: py main.py')
