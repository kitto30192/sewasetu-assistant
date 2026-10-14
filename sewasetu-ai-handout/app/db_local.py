import sqlite3
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'app', 'sewasetu_local.db')

def init_local_db():
    pass

class SQLiteCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = -1
        self.lastrowid = None
        self._fake_return = None

    def execute(self, sql, params=None):
        self._fake_return = None
        params = list(params) if params else []
        
        # Handle IN %s
        in_match = re.search(r'IN\s+%s', sql, re.IGNORECASE)
        while in_match:
            count_before = sql[:in_match.start()].count('%s')
            if count_before < len(params) and isinstance(params[count_before], tuple):
                tuple_val = params[count_before]
                placeholders = ', '.join(['?'] * len(tuple_val))
                sql = sql[:in_match.start()] + f"IN ({placeholders})" + sql[in_match.end():]
                params = params[:count_before] + list(tuple_val) + params[count_before+1:]
            else:
                break
            in_match = re.search(r'IN\s+%s', sql, re.IGNORECASE)

        # Replace remaining %s with ?
        sql = sql.replace('%s', '?')
        
        # Handle JSONB -> text
        sql = sql.replace('::jsonb', '')

        # Handle RETURNING
        returning_match = re.search(r'\bRETURNING\s+(.+)$', sql, re.IGNORECASE)
        returning_cols = []
        is_insert = bool(re.match(r'^\s*INSERT\s+INTO', sql, re.IGNORECASE))
        is_update = bool(re.match(r'^\s*UPDATE\s+', sql, re.IGNORECASE))
        is_delete = bool(re.match(r'^\s*DELETE\s+FROM', sql, re.IGNORECASE))
        
        returning_result = None

        if returning_match:
            returning_cols = [c.strip() for c in returning_match.group(1).split(',')]
            sql = sql[:returning_match.start()].strip()
            
            if is_update or is_delete:
                where_match = re.search(r'\bWHERE\s+(.+)$', sql, re.IGNORECASE)
                if where_match:
                    where_clause = where_match.group(1)
                    table_name = ""
                    if is_update:
                        table_match = re.search(r'^\s*UPDATE\s+(\w+)\s+SET', sql, re.IGNORECASE)
                        table_name = table_match.group(1) if table_match else ""
                    else:
                        table_match = re.search(r'^\s*DELETE\s+FROM\s+(\w+)', sql, re.IGNORECASE)
                        table_name = table_match.group(1) if table_match else ""
                        
                    where_param_count = where_clause.count('?')
                    where_params = params[-where_param_count:] if where_param_count > 0 else []
                    
                    sel_sql = f"SELECT {', '.join(returning_cols)} FROM {table_name} WHERE {where_clause}"
                    self.cursor.execute(sel_sql, where_params)
                    returning_result = self.cursor.fetchone()

        self.cursor.execute(sql, params)
        self.rowcount = self.cursor.rowcount
        self.lastrowid = self.cursor.lastrowid
        
        if returning_match:
            if is_insert:
                if len(returning_cols) == 1 and returning_cols[0].lower() == 'id':
                    self._fake_return = (self.lastrowid,)
                else:
                    table_match = re.search(r'^\s*INSERT\s+INTO\s+(\w+)', sql, re.IGNORECASE)
                    table_name = table_match.group(1) if table_match else ""
                    sel_sql = f"SELECT {', '.join(returning_cols)} FROM {table_name} WHERE rowid = ?"
                    self.cursor.execute(sel_sql, [self.lastrowid])
                    self._fake_return = self.cursor.fetchone()
            elif is_update or is_delete:
                self._fake_return = returning_result

    def fetchone(self):
        if self._fake_return is not None:
            ret = self._fake_return
            self._fake_return = None
            return ret
        return self.cursor.fetchone()

    def fetchall(self):
        if self._fake_return is not None:
            ret = [self._fake_return]
            self._fake_return = None
            return ret
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()

class SQLiteConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return SQLiteCursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()
        
    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return SQLiteConnectionWrapper(conn)
