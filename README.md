# Eleven Store — License Bot

نسخه واقعی Eleven Store برای فروش **لایسنس ربات فروش پنل**.

- هر خرید یک Instance مستقل از `customer_template` می‌سازد.
- Bot Token با `getMe` اعتبارسنجی می‌شود.
- Instance با محیط جداگانه اجرا می‌شود تا Conflict بین توکن‌ها ایجاد نشود.
- بکاپ SQL برای Instanceها ساخته می‌شود.
- انقضا باعث بکاپ و توقف Instance می‌شود.
- تست پنل در این پروژه وجود ندارد؛ تست پنل متعلق به Eleven Pro است.

## نصب روی Ubuntu
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python3 main.py
```

## systemd
`deploy/eleven-store-bot.service` را نصب و مسیرها را اصلاح کنید.

## Windows PowerShell
```powershell
py -m pip install -r .\requirements.txt
Copy-Item .env.example .env
notepad .env
py .\main.py
```
