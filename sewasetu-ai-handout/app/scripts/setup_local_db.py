import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'sewasetu_local.db')
SCHEMA_SQ = os.path.join(BASE_DIR, 'schema_sqlite.sql')

def setup():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Removed old db")
        
    print("Converting schema...")
    subprocess.run([sys.executable, os.path.join(BASE_DIR, 'scripts', 'convert_schema.py')], check=True)
    
    print("Running schema...")
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_SQ, 'r') as f:
        conn.executescript(f.read())
    conn.close()
    
    print("Converting and loading seed data...")
    subprocess.run([sys.executable, os.path.join(BASE_DIR, 'scripts', 'convert_seed.py')], check=True)
    print("Setup complete.")

if __name__ == '__main__':
    setup()
