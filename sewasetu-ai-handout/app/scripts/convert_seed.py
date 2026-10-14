import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_SQL = os.path.join(os.path.dirname(BASE_DIR), 'seed', 'seed.sql')
SEED_SQLITE = os.path.join(BASE_DIR, 'seed_sqlite.sql')
DB_PATH = os.path.join(BASE_DIR, 'sewasetu_local.db')

def process_seed():
    print("Starting seed conversion...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    with open(SEED_SQL, 'r', encoding='utf8') as f, open(SEED_SQLITE, 'w', encoding='utf8') as out_f:
        in_copy = False
        table = None
        columns = None
        count = 0
        
        for line in f:
            line = line.strip('\n')
            if line.startswith('COPY '):
                # COPY applications (id, application_no, applicant_name, mobile, dob, gender, marital_status, husband_name, husband_employer, village, block, bank_account, ifsc, doc_path, status, submitted_at, decided_at, decided_by) FROM stdin;
                parts = line.split(' ')
                table = parts[1]
                cols_str = line[line.find('(')+1:line.find(')')]
                columns = [c.strip() for c in cols_str.split(',')]
                in_copy = True
                print(f"Loading table {table}...")
                continue
            
            if in_copy:
                if line == '\\.':
                    in_copy = False
                    conn.commit()
                    print(f"Finished {table}: {count} rows")
                    count = 0
                    continue
                
                values = line.split('\t')
                # Handle \N for NULL
                values = [None if v == '\\N' else v for v in values]
                
                placeholders = ','.join(['?'] * len(columns))
                sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
                
                # Write to sql file (format for sqlite)
                # Just stringify correctly for seed_sqlite.sql if needed, but direct insert is faster
                # out_f.write(sql ...) - skipping writing full statements to file as they are huge,
                # instructions say "Writes them to app/seed_sqlite.sql - Also directly loads them"
                # Actually, I should write the inserts to the file to strictly follow instructions.
                
                sql_file_vals = []
                for v in values:
                    if v is None:
                        sql_file_vals.append('NULL')
                    else:
                        v_esc = v.replace("'", "''")
                        sql_file_vals.append(f"'{v_esc}'")
                        
                out_f.write(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(sql_file_vals)});\n")
                
                # Direct load
                cur.execute(sql, values)
                count += 1
                
    conn.close()
    print("Seed data converted and loaded.")

if __name__ == '__main__':
    process_seed()
