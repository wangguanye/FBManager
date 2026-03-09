import sqlite3
import os

DB_PATH = "fb_manager.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(fb_accounts)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "cookie_encrypted" not in columns:
            print("Adding cookie_encrypted column to fb_accounts...")
            cursor.execute("ALTER TABLE fb_accounts ADD COLUMN cookie_encrypted TEXT")
            conn.commit()
            print("Migration successful.")
        else:
            print("Column cookie_encrypted already exists.")
            
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
