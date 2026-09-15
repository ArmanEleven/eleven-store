# PasarGuard Dealer Bot V15 — Pre Mini-App Core

V15 is the stabilization release before Mini App work. It keeps the existing V14 sales flow and adds the remaining core customer/finance/operations features without adding referral, cashback, VIP, or reseller systems.

## Included
- Suggested plans and custom plans
- Unlimited-volume monthly pricing
- Card-to-card payments with optional delayed auto approval
- Receipt review with duplicate-approval protection
- Wallet payment with reserved balance and automatic refund on provisioning failure/rejection
- User wallet top-up by receipt, with atomic admin approval/rejection
- Coupon redemption inside checkout (percent/fixed, limits, expiry, per-user limits)
- Service renewal (days for limited services, months for unlimited services)
- Service volume increase with payment/approval before PasarGuard change
- Service revoke with confirmation
- Admin user details, wallet management, block/unblock
- Panel connection test before saving
- Detailed admin input instructions: explanation + constraints + example
- Reports group registration via `/register_reports` inside the group; no manual group ID entry
- Report topics for users, purchases, payments, panels, wallet, products, admins, errors, system
- Important report events wired into report topics
- Database backup and guarded restore with `before-restore` copy
- Audit logs
- Atomic order processing guard to prevent duplicate provisioning
- Product capacity claim before provisioning and rollback on API failure
- Password generator that satisfies the PasarGuard password policy
- Colored Telegram buttons

## Intentionally not included
- Referral
- Cashback
- VIP tiers
- Reseller / multi-level reseller system

Those are deliberately postponed. The next major phase after this core is Mini App.

## Important
Preserve your existing `.env` and `database/app.db` when replacing the project. Do not overwrite them with files from the ZIP.

Service operations use the PasarGuard admin API. If a specific PasarGuard release rejects an endpoint, the bot reports the API error and does not silently mark the local operation successful.

## Replace on Windows
```powershell
cd D:\pasarguard-bot

Copy-Item .env .env.backup -Force
Copy-Item database\app.db database\app.db.backup -Force

# Extract this ZIP over D:\pasarguard-bot while keeping .env and database\app.db.
# Then:
.\run.ps1
```

## Fresh install
```powershell
cd D:\pasarguard-bot
.\run.ps1
```

`run.ps1` creates the virtual environment, installs requirements, runs setup when `.env` is missing, compiles the project, runs local tests, and starts the bot.

## Reports
Inside the desired Telegram group:
1. Enable Topics / Forum mode.
2. Add the bot and make it Administrator.
3. Send `/register_reports` in that same group.
4. No group ID lookup or manual ID entry is required.

## Safety
Never publish the bot token, PasarGuard credentials, database, or `.env`. If a real token/credential has been exposed in a public log, rotate it.
