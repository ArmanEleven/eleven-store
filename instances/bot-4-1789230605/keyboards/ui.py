from telegram import InlineKeyboardButton,InlineKeyboardMarkup
def b(t,c,s='primary'):
 kw={'text':t,'callback_data':c,'style':s}
 return InlineKeyboardButton(**kw)
def home(admin=False):
 rows=[[b('📦 تهیه پنل','buy_panel','primary')],[b('🖥️ پنل‌های من','my_panels','primary'),b('💰 کیف پول','wallet')],[b('👤 حساب من','account'),b('💬 پشتیبانی','support')]]
 if admin: rows.append([b('⚙️ پنل مدیریت','admin','primary')])
 return InlineKeyboardMarkup(rows)
def admin_menu():
 return InlineKeyboardMarkup([[b('👥 کاربران','admin_users','primary'),b('🖥️ پنل‌ها','admin_panels','primary')],[b('📦 محصولات','admin_products','primary'),b('⚙️ پلن دلخواه','admin_custom','primary')],[b('💰 مرکز مالی','admin_finance','primary')],[b('⏳ سفارش‌های در انتظار','admin_pending','primary')],[b('📊 گزارش‌ها','admin_reports','primary'),b('⚙️ تنظیمات','admin_settings')],[b('↩️ بازگشت','home')]])
def back(c='admin'): return InlineKeyboardMarkup([[b('↩️ بازگشت',c)]])
