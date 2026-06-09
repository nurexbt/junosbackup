"""One-time migration: add SSH columns and collect_log table to existing DB."""
import sqlite3

DB = 'instance/juniper_configs.db'
conn = sqlite3.connect(DB)
cur  = conn.cursor()

# ── Device table: add SSH columns ─────────────────────────────────────────────
cols = [row[1] for row in cur.execute('PRAGMA table_info(device)').fetchall()]
print('Existing device columns:', cols)

new_cols = [
    ('ssh_username', 'TEXT'),
    ('ssh_password', 'TEXT'),
    ('ssh_port',     'INTEGER DEFAULT 22'),
    ('ssh_enabled',  'INTEGER DEFAULT 0'),
]
for col, typ in new_cols:
    if col not in cols:
        cur.execute(f'ALTER TABLE device ADD COLUMN {col} {typ}')
        print(f'  Added: {col}')
    else:
        print(f'  Already exists: {col}')

# ── Config table: add source column ──────────────────────────────────────────
cfg_cols = [row[1] for row in cur.execute('PRAGMA table_info(config)').fetchall()]
if 'source' not in cfg_cols:
    cur.execute("ALTER TABLE config ADD COLUMN source TEXT DEFAULT 'manual'")
    print('  Added: config.source')
else:
    print('  Already exists: config.source')

# ── collect_log table ─────────────────────────────────────────────────────────
cur.execute('''
CREATE TABLE IF NOT EXISTS collect_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES device(id),
    run_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    status    TEXT,
    message   TEXT,
    config_id INTEGER REFERENCES config(id)
)''')
print('collect_log table ready')

conn.commit()
conn.close()
print('Migration complete.')
