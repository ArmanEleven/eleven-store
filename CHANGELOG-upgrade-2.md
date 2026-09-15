# Eleven Store — Upgrade 2

## Scope

Upgrade 2 continues the existing Upgrade 1 codebase. No full rewrite was performed and existing database tables/data were preserved.

## Implemented

### 1. Dynamic product catalog — final audit
- Eleven Store admin product creation now supports:
  - name
  - price
  - volume (GB, `0` = unlimited)
  - duration in days (`0` = unlimited)
  - maximum users (`0` = unlimited)
  - sales capacity (`0` = unlimited)
  - description
- Product editing now exposes volume, duration, max users, capacity, price, name and description.
- Product screens show volume/duration explicitly.
- The invalid state where both volume and duration are unlimited is rejected.
- Existing legacy product/license resolution remains intact.

### 2. Unlimited volume vs duration
- Volume and duration remain independent fields.
- Unlimited volume with a finite duration is allowed.
- Both unlimited simultaneously is rejected in the product catalog.

### 3. Configurable Trial system in customer_template
- Added one-time Trial flow for users.
- Default Trial: 1 day / 5GB.
- Admin can enable/disable Trial.
- Admin can change Trial duration using minutes, hours or days.
- Admin can change Trial volume; `0` means unlimited.
- Trial is isolated from paid products/orders.
- A user can claim the Trial only once.
- Trial services expire independently and are cleaned up by the background job.

### 4. Random service credentials
- Random service usernames now use multiple human-friendly prefixes and avoid known username collisions where possible.
- Added an 8-digit random service identifier stored in the database as `service_code`.
- The real PasarGuard administrator ID is still kept separately as `pg_admin_id`; it is assigned by PasarGuard and is not faked or overwritten by the local random service code.
- Existing paid services also receive a service code when provisioned.

### 5. Database safety
- Added `service_code` to `services` using additive schema migration.
- Added `trial_claims` with one claim per user.
- Existing data is preserved; no DROP/RESET operation was introduced.

### 6. Trial expiry
- Background job now detects expired Trial services, attempts to delete the corresponding PasarGuard admin, and marks the local service expired.
- A cleanup failure is logged without crashing the bot.

## Verification performed

- `py_compile` passed for all Python files in the release tree.
- Root `test_project.py`: `ALL LOCAL TESTS PASSED`.
- `customer_template/test_project.py`: `ALL LOCAL TESTS PASSED`.
- Customer database migration was tested on a copy of the existing database.
- Trial settings/table and `service_code` migration were verified.
- No Telegram live API test was possible from this environment.

## Not silently claimed as live-tested

The following still require a real Telegram/PasarGuard environment:
- actual Trial creation against a live PasarGuard panel
- actual Trial expiry cleanup against a live panel
- real Telegram callback/message flows
- real Store restart with production instances
- real payment and receipt delivery
- actual PasarGuard-assigned numeric admin IDs

## Security

Real `.env` files were not included in the release package. `.env.example` templates remain where present. Telegram tokens and credentials were not added to this release.
