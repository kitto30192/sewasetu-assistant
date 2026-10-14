import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PG = os.path.join(BASE_DIR, 'schema.sql')
SCHEMA_SQ = os.path.join(BASE_DIR, 'schema_sqlite.sql')

with open(SCHEMA_PG, 'r') as f:
    schema = f.read()

# Conversions
schema = schema.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
import re
schema = re.sub(r'VARCHAR\(\d+\)', 'TEXT', schema)
schema = schema.replace('JSONB', 'TEXT')
schema = schema.replace('TIMESTAMP', 'TEXT')
schema = schema.replace('DATE', 'TEXT')
schema = schema.replace('CREATE INDEX IF NOT EXISTS', 'CREATE INDEX')

with open(SCHEMA_SQ, 'w') as f:
    f.write(schema)

print(f"Created {SCHEMA_SQ}")
