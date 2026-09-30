# Eleven Store

نسخه عملیاتی Eleven Store برای فروش و مدیریت **لایسنس ربات فروش پنل**.

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
python3 bot.py
```

## systemd
`deploy/eleven-store-bot.service` را نصب و مسیرها را اصلاح کنید.

## Windows PowerShell
```powershell
py -m pip install -r .\requirements.txt
Copy-Item .env.example .env
notepad .env
py .\bot.py
```


## ساختار پروژه

- `bot.py` — هسته ربات اصلی Eleven Store
- `customer_template/` — قالب رباتی که برای هر مشتری ساخته می‌شود
- `database/` — لایه دسترسی به دیتابیس
- `instances/` — نمونه‌های ساخته‌شده مشتریان
- `backups/` — فایل‌های پشتیبان
- `deploy/` — فایل‌های systemd برای استقرار روی سرور
- `install.ps1` — نصب و اجرای سریع در Windows

> فایل‌های واقعی `.env` و اطلاعات حساس نباید وارد Git شوند.
