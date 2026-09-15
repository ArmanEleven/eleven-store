import os, tempfile
from pathlib import Path

def test_db():
    with tempfile.TemporaryDirectory() as d:
        import database.core as core
        old=core.DB_PATH; core.DB_PATH=Path(d)/'database'/'app.db'
        core.init_database()
        from database.users import upsert_user, get_user_by_tid
        upsert_user(999,'tester','Tester')
        u=get_user_by_tid(999)
        assert u and u['telegram_id']==999 and u['balance']==0
        core.DB_PATH=old

def test_imports():
    import database.admins, database.users, database.panels, database.products, database.finance, database.orders, database.reports
    import pasarguard

if __name__=='__main__':
    test_imports(); test_db(); print('ALL LOCAL TESTS PASSED')
