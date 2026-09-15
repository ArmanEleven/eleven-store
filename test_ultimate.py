from pathlib import Path
import ast, zipfile, tempfile, subprocess, sys, os, sqlite3, json
ROOT=Path(__file__).resolve().parent

def check_compile():
    files=[ROOT/'main.py',ROOT/'config.py',ROOT/'pasarguard.py']+list((ROOT/'database').glob('*.py'))+list((ROOT/'keyboards').glob('*.py'))
    for f in files: compile(f.read_text(encoding='utf-8'),str(f),'exec')

def check_schema():
    db=ROOT/'database'/'app.db'
    if db.exists(): db.unlink()
    import database.core as core
    core.init_database()
    c=core.get_connection(); names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'expiry_notifications' in names and 'bots' in names and 'transactions' in names
    cols={r[1] for r in c.execute('PRAGMA table_info(bots)')}
    assert {'expired_at','deleted_at','bot_token'} <= cols
    c.close(); db.unlink(missing_ok=True)

def check_source_guards():
    s=(ROOT/'main.py').read_text(encoding='utf-8')
    assert "executescript(script)" not in s
    assert "tempfile.mktemp" not in s
    assert "status='expired'" in s
    assert "timedelta(days=3)" in s
    assert "hour2-" in s and "daily-" in s
    assert "fernet1:" in s
    assert "eleven-store-config-backup" in s
    assert ".json" in s

def check_no_release_secrets():
    assert not (ROOT/'.env').exists()
    assert not (ROOT/'.venv').exists()
    assert not (ROOT/'bot.py').exists()
    assert not (ROOT/'miniapp').exists()
    assert not (ROOT/'webapp.py').exists()
    assert not list((ROOT/'database').glob('*.db'))

def check_zip_clean():
    out=ROOT.parent/'Eleven-Store-V2-Production.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob('*'):
            if p.is_file() and not any(part in {'.venv','__pycache__'} for part in p.parts):
                z.write(p,p.relative_to(ROOT.parent))
    with zipfile.ZipFile(out) as z:
        names=z.namelist()
        assert not any(Path(n).name=='.env' for n in names)
        assert not any('.venv/' in n or '__pycache__/' in n for n in names)
        assert not any(n.endswith('.db') for n in names)
    return out

if __name__=='__main__':
    check_compile(); check_schema(); check_source_guards(); check_no_release_secrets(); out=check_zip_clean(); print('ULTIMATE_STORE_TESTS: PASS'); print(out)
