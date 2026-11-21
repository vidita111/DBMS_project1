import sqlite3
import mysql.connector
import os

from pathlib import Path
from dotenv import load_dotenv

# Load database credentials
load_dotenv()

# Existing SQLite database
BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "repo" / "database" / "nsut_exam.db"

# Tables in foreign-key dependency order
TABLES = [
    "branch",
    "student",
    "faculty",
    "subject",
    "room",
    "exam_slot",
    "exam",
    "seat_allocation",
    "invigilation"
]


def migrate_data():

    if not SQLITE_PATH.exists():
        print("ERROR: SQLite database not found!")
        print(SQLITE_PATH)
        return

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_cursor = sqlite_conn.cursor()

    # Connect to MySQL
    mysql_conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "nsut_exam")
    )

    mysql_cursor = mysql_conn.cursor()

    try:
        # Prevent accidental duplicate imports
        for table in TABLES:
            mysql_cursor.execute(
                f"SELECT COUNT(*) FROM `{table}`"
            )

            if mysql_cursor.fetchone()[0] > 0:
                raise Exception(
                    f"Table {table} is not empty. "
                    "Migration stopped to prevent duplicates."
                )

        print("\nStarting SQLite to MySQL migration...\n")

        for table in TABLES:

            # Read records from SQLite
            sqlite_cursor.execute(
                f'SELECT * FROM "{table}"'
            )

            rows = sqlite_cursor.fetchall()

            if not rows:
                print(f"{table}: 0 records")
                continue

            # Get column names
            columns = [
                description[0]
                for description in sqlite_cursor.description
            ]

            column_names = ", ".join(
                f"`{column}`" for column in columns
            )

            placeholders = ", ".join(
                ["%s"] * len(columns)
            )

            query = (
                f"INSERT INTO `{table}` "
                f"({column_names}) "
                f"VALUES ({placeholders})"
            )

            # Insert records into MySQL
            mysql_cursor.executemany(query, rows)

            print(f"{table}: {len(rows)} records imported")

        mysql_conn.commit()

        print("\nSUCCESS! All records imported.")

    except Exception as error:

        mysql_conn.rollback()

        print("\nMIGRATION FAILED:")
        print(error)

    finally:

        sqlite_cursor.close()
        sqlite_conn.close()

        mysql_cursor.close()
        mysql_conn.close()


if __name__ == "__main__":
    migrate_data()