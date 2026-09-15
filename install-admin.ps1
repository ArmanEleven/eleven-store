$ErrorActionPreference = "Stop"

$Project = "D:\eleven-pro-sales-bot"
Set-Location $Project

Write-Host "Eleven Store Admin Upgrade" -ForegroundColor Cyan

if (!(Test-Path ".\bot.py")) {
    Write-Host "bot.py not found." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------
# BACKUP
# ---------------------------------------------------------

$backup = ".\bot.py.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Copy-Item ".\bot.py" $backup -Force

Write-Host "Backup created: $backup" -ForegroundColor Green

# ---------------------------------------------------------
# CREATE PYTHON PATCHER
# ---------------------------------------------------------

$patch = @'
from pathlib import Path
import py_compile

p = Path("bot.py")
s = p.read_text(encoding="utf-8")

if "DEFAULT_TEXTS = {" in s:
    print("TEXT_SYSTEM_ALREADY_EXISTS")
    py_compile.compile("bot.py", doraise=True)
    raise SystemExit(0)

marker = "def button_style(text):"

if marker not in s:
    raise RuntimeError("button_style marker not found")

feature = r'''
# =========================================================
# ELEVEN STORE - EDITABLE TEXT SYSTEM
# =========================================================

DEFAULT_TEXTS = {
    "start": "Welcome to Eleven Store!",
    "home": "Main Menu",
    "build": "🤖 Build Bot\n\n📦 Choose your plan:",
    "wallet": "💰 Wallet\n\nBalance: {balance:,} Toman",
    "manage": "⚙️ Bot Management\n\nChoose a bot:",
    "manage_empty": "⚙️ You don't have any bots yet.",
    "review": "🔍 Review Information\n\nPlan: {plan}\nPrice: {price:,} Toman\nAdmin ID: {admin_id}\n\nIs everything correct?",
    "success": "✅ Operation completed successfully.",
    "error": "❌ Something went wrong.",
    "admin_denied": "🚫 Access denied.",
    "trial_used": "🚫 You have already used your trial.",
    "trial_full": "⏳ Trial capacity is currently full.",
    "trial_confirm": "🧪 Panel Test\n\nVolume: {gb:g} GB\nDuration: {hours:g} hours\n\nContinue?",
    "support": "🆘 Support\n\nSend your message.",
    "support_success": "✅ Your message was sent to support.",
    "referral": "👥 Referral\n\nLink:\n{link}\n\nInvited: {count}\nEarned: {earned:,} Toman",
    "admin_panel": "👑 Admin Panel\n\nUsers: {users}\nBots: {bots}\nTrials: {trials}\nOrders: {orders}",
    "products": "🛒 Products and Plans\n\n{plans}",
    "test_settings": "🧪 Test Settings\n\nVolume: {gb:g} GB\nDuration: {hours:g} hours\nConcurrent: {concurrent}\n\nMaximum: 5 GB / 24 hours",
    "setting_saved": "✅ Settings saved.",
    "admin_id_error": "❌ Admin ID must contain numbers only.",
    "token_error": "❌ Invalid Bot Token.",
    "delete": "🗑 Delete Bot\n\nA final SQL backup will be created before deletion.\n\nSend DELETE to confirm.",
    "delete_error": "❌ Send DELETE to confirm.",
    "deleted": "🗑 Bot deleted.",
    "backup": "💾 Backup\n\nYour SQL backup is ready.",
    "import": "📥 Import Backup\n\nSend the SQL backup file.",
    "transfer": "🔀 Transfer Bot\n\nSend the new owner's numeric Telegram ID.",
    "transfer_success": "✅ Bot transferred successfully.",
    "change_plan": "📦 Choose the new plan.",
    "renew": "📅 Choose renewal duration.",
    "card_payment": "💳 Payment Information\n\nHolder: {holder}\nCard: {card}\n\nAfter payment, send the receipt.",
    "card_added": "✅ Bank card added.",
    "card_deleted": "🗑 Bank card deleted."
}


def init_bot_texts():
    c = conn()

    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_texts(
            text_key TEXT PRIMARY KEY,
            text_value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for key, value in DEFAULT_TEXTS.items():
        c.execute(
            "INSERT OR IGNORE INTO bot_texts(text_key,text_value) VALUES(?,?)",
            (key, value)
        )

    c.commit()
    c.close()


def get_text(key, **kwargs):
    try:
        c = conn()

        row = c.execute(
            "SELECT text_value FROM bot_texts WHERE text_key=?",
            (key,)
        ).fetchone()

        c.close()

        value = row["text_value"] if row else DEFAULT_TEXTS.get(key, key)

    except Exception:
        value = DEFAULT_TEXTS.get(key, key)

    try:
        return value.format(**kwargs)
    except Exception:
        return value


def save_text(key, value):
    c = conn()

    c.execute("""
        INSERT INTO bot_texts(text_key,text_value,updated_at)
        VALUES(?,?,CURRENT_TIMESTAMP)

        ON CONFLICT(text_key)
        DO UPDATE SET
            text_value=excluded.text_value,
            updated_at=CURRENT_TIMESTAMP
    """, (key, value))

    c.commit()
    c.close()


def reset_text(key):
    if key in DEFAULT_TEXTS:
        save_text(key, DEFAULT_TEXTS[key])


def reset_all_texts():
    for key, value in DEFAULT_TEXTS.items():
        save_text(key, value)


# =========================================================
# BANK CARDS
# =========================================================

def init_bank_cards():
    c = conn()

    c.execute("""
        CREATE TABLE IF NOT EXISTS bank_cards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holder_name TEXT NOT NULL,
            card_number TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.commit()
    c.close()


def get_bank_cards():
    c = conn()

    rows = c.execute("""
        SELECT id,holder_name,card_number,is_active
        FROM bank_cards
        ORDER BY id DESC
    """).fetchall()

    c.close()

    return rows


def add_bank_card(holder, number):
    c = conn()

    c.execute(
        "INSERT INTO bank_cards(holder_name,card_number,is_active) VALUES(?,?,1)",
        (holder.strip(), number.strip())
    )

    c.commit()
    c.close()


def delete_bank_card(card_id):
    c = conn()

    c.execute(
        "DELETE FROM bank_cards WHERE id=?",
        (card_id,)
    )

    c.commit()
    c.close()


def bank_cards_message():
    rows = get_bank_cards()

    if not rows:
        return "💳 Bank Cards\n\nNo cards registered."

    result = ["💳 <b>Bank Cards</b>\n"]

    for r in rows:

        status = "🟢 Active" if r["is_active"] else "🔴 Disabled"

        result.append(
            f"#{r['id']}\n"
            f"👤 {r['holder_name']}\n"
            f"💳 <code>{r['card_number']}</code>\n"
            f"{status}\n"
        )

    return "\n".join(result)


try:
    init_bot_texts()
    init_bank_cards()
except Exception:
    pass

# =========================================================
# END ADMIN SYSTEM
# =========================================================

'''

s = s.replace(
    marker,
    feature + marker,
    1
)

# ---------------------------------------------------------
# ADMIN MENU
# ---------------------------------------------------------

old_admin = '''[("🛒 محصولات و پلن‌ها","admin_products")],[("🧪 تنظیمات تست","admin_test")],[("🔙 بازگشت","back")]'''

new_admin = '''[("🛒 محصولات و پلن‌ها","admin_products")],
            [("✏️ مدیریت کامل متن‌ها","admin_texts")],
            [("💳 کارت‌های بانکی","admin_cards")],
            [("🧪 تنظیمات تست","admin_test")],
            [("🔙 بازگشت","back")]'''

if old_admin in s:
    s = s.replace(
        old_admin,
        new_admin,
        1
    )

# ---------------------------------------------------------
# CALLBACK ROUTES
# ---------------------------------------------------------

needle = '    if d=="admin_products":'

if needle not in s:
    raise RuntimeError("admin_products callback not found")

routes = r'''
    # =====================================================
    # ADMIN TEXT MANAGER
    # =====================================================

    if d=="admin_texts":

        if q.from_user.id != OWNER_ID:
            return await q.answer(
                get_text("admin_denied"),
                show_alert=True
            )

        rows = []

        for key in DEFAULT_TEXTS:
            rows.append([
                (f"✏️ {key}", f"edittext:{key}")
            ])

        rows.append([
            ("🔄 Reset All Texts", "resetalltexts")
        ])

        rows.append([
            ("🔙 Back", "admin")
        ])

        return await q.edit_message_text(
            "✏️ <b>Text Manager</b>\n\nChoose a text:",
            parse_mode="HTML",
            reply_markup=markup(rows)
        )


    if d=="resetalltexts":

        if q.from_user.id != OWNER_ID:
            return await q.answer(
                get_text("admin_denied"),
                show_alert=True
            )

        reset_all_texts()

        return await q.edit_message_text(
            "✅ All texts reset.",
            reply_markup=markup([
                [("✏️ Text Manager","admin_texts")],
                [("🔙 Back","admin")]
            ])
        )


    if d.startswith("edittext:"):

        if q.from_user.id != OWNER_ID:
            return await q.answer(
                get_text("admin_denied"),
                show_alert=True
            )

        key = d.split(":",1)[1]

        if key not in DEFAULT_TEXTS:
            return

        ctx.user_data["state"] = "edit_text"
        ctx.user_data["edit_text_key"] = key

        current = get_text(key)

        preview = (
            current
            .replace("&","&amp;")
            .replace("<","&lt;")
            .replace(">","&gt;")
        )

        return await q.edit_message_text(
            "✏️ <b>Edit Text</b>\n\n"
            f"Key: <code>{key}</code>\n\n"
            f"<blockquote>{preview}</blockquote>\n\n"
            "Send the new text:",
            parse_mode="HTML",
            reply_markup=markup([
                [("🔄 Reset","resettext:"+key)],
                [("🔙 Back","admin_texts")]
            ])
        )


    if d.startswith("resettext:"):

        if q.from_user.id != OWNER_ID:
            return await q.answer(
                get_text("admin_denied"),
                show_alert=True
            )

        key = d.split(":",1)[1]

        reset_text(key)

        return await q.edit_message_text(
            "✅ Text reset.",
            reply_markup=markup([
                [("✏️ Text Manager","admin_texts")]
            ])
        )


    # =====================================================
    # BANK CARDS
    # =====================================================

    if d=="admin_cards":

        if q.from_user.id != OWNER_ID:
            return await q.answer(
                get_text("admin_denied"),
                show_alert=True
            )

        rows = [
            [("➕ Add Card","addcard")]
        ]

        for r in get_bank_cards():

            rows.append([
                (
                    f"🗑 Delete #{r['id']} - {r['holder_name']}",
                    f"delcard:{r['id']}"
                )
            ])

        rows.append([
            ("🔙 Back","admin")
        ])

        return await q.edit_message_text(
            bank_cards_message(),
            parse_mode="HTML",
            reply_markup=markup(rows)
        )


    if d=="addcard":

        if q.from_user.id != OWNER_ID:
            return await q.answer(
                get_text("admin_denied"),
                show_alert=True
            )

        ctx.user_data["state"] = "card_name"

        return await q.edit_message_text(
            "💳 <b>Add Bank Card</b>\n\n"
            "Send the card holder name.\n\n"
            "Example:\n"
            "Ali Rezaei",
            parse_mode="HTML",
            reply_markup=markup([
                [("🔙 Cancel","admin_cards")]
            ])
        )


    if d.startswith("delcard:"):

        if q.from_user.id != OWNER_ID:
            return await q.answer(
                get_text("admin_denied"),
                show_alert=True
            )

        card_id = int(
            d.split(":",1)[1]
        )

        delete_bank_card(card_id)

        return await q.edit_message_text(
            get_text("card_deleted"),
            reply_markup=markup([
                [("💳 Bank Cards","admin_cards")],
                [("🔙 Admin Panel","admin")]
            ])
        )

'''

s = s.replace(
    needle,
    routes + needle,
    1
)

# ---------------------------------------------------------
# TEXT STATES
# ---------------------------------------------------------

needle2 = '    state=ctx.user_data.get("state"); t=(update.message.text or "").strip(); u=user(update.effective_user)'

if needle2 not in s:
    raise RuntimeError("text handler not found")

state_patch = r'''
    # =====================================================
    # EDIT TEXT
    # =====================================================

    if state=="edit_text" and update.effective_user.id==OWNER_ID:

        key = ctx.user_data.get(
            "edit_text_key"
        )

        if key in DEFAULT_TEXTS:
            save_text(
                key,
                update.message.text or ""
            )

        ctx.user_data.clear()

        return await update.message.reply_text(
            "✅ Text saved.",
            reply_markup=markup([
                [("✏️ Text Manager","admin_texts")]
            ])
        )


    # =====================================================
    # ADD CARD - HOLDER
    # =====================================================

    if state=="card_name" and update.effective_user.id==OWNER_ID:

        ctx.user_data["card_holder"] = t
        ctx.user_data["state"] = "card_number"

        return await update.message.reply_text(
            "💳 Send the 16 digit card number.\n\n"
            "Example:\n"
            "<code>6037991234567890</code>",
            parse_mode="HTML"
        )


    # =====================================================
    # ADD CARD - NUMBER
    # =====================================================

    if state=="card_number" and update.effective_user.id==OWNER_ID:

        number = "".join(
            ch for ch in t
            if ch.isdigit()
        )

        if len(number) != 16:

            return await update.message.reply_text(
                "❌ Card number must contain exactly 16 digits."
            )

        add_bank_card(
            ctx.user_data.get(
                "card_holder",
                ""
            ),
            number
        )

        ctx.user_data.clear()

        return await update.message.reply_text(
            get_text("card_added"),
            reply_markup=markup([
                [("💳 Bank Cards","admin_cards")],
                [("🔙 Admin Panel","admin")]
            ])
        )

'''

s = s.replace(
    needle2,
    needle2 + "\n" + state_patch,
    1
)

# ---------------------------------------------------------
# STARTUP
# ---------------------------------------------------------

s = s.replace(
    'init_db(); app=Application.builder()',
    'init_db(); init_bot_texts(); init_bank_cards(); app=Application.builder()',
    1
)

# ---------------------------------------------------------
# MAIN TEXT
# ---------------------------------------------------------

s = s.replace(
    'await update.message.reply_text("👋 به Eleven Store خوش اومدی!\\n\\nاز منوی زیر می‌تونی رباتت رو بسازی، مدیریت کنی، تست بگیری و کیف پولت رو مدیریت کنی.",reply_markup=home(update.effective_user.id))',
    'await update.message.reply_text(get_text("start"),reply_markup=home(update.effective_user.id))'
)

s = s.replace(
    'await q.edit_message_text("🏠 منوی اصلی",reply_markup=home(q.from_user.id))',
    'await q.edit_message_text(get_text("home"),reply_markup=home(q.from_user.id))'
)

# ---------------------------------------------------------
# COMPILE
# ---------------------------------------------------------

py_compile.compile(
    "bot.py",
    doraise=True
)

print("PATCH_SUCCESS")

'@

$patch | Set-Content ".\_admin_patch.py" -Encoding UTF8

Write-Host "Applying patch..." -ForegroundColor Yellow

py .\_admin_patch.py

if ($LASTEXITCODE -ne 0) {

    Write-Host "Patch failed." -ForegroundColor Red

    Remove-Item ".\_admin_patch.py" -Force -ErrorAction SilentlyContinue

    Write-Host "Backup remains available:" -ForegroundColor Yellow
    Write-Host $backup

    exit 1
}

Remove-Item ".\_admin_patch.py" -Force

Write-Host "Installing requirements..." -ForegroundColor Yellow

py -m pip install -r .\requirements.txt

Write-Host "Running syntax check..." -ForegroundColor Yellow

py -m py_compile .\bot.py

if ($LASTEXITCODE -ne 0) {

    Write-Host "Syntax check failed." -ForegroundColor Red
    Write-Host "Backup: $backup"

    exit 1
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "INSTALLATION SUCCESSFUL" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "Backup:"
Write-Host $backup -ForegroundColor Yellow
Write-Host ""
Write-Host "Run bot with:"
Write-Host "py .\bot.py" -ForegroundColor Cyan