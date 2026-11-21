
import os
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

db = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    port=int(os.getenv("MYSQL_PORT", 3306)),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE")
)

cursor = db.cursor()

print("Connected to MySQL...")

# Generate the password hash only once
student_hash = generate_password_hash(
    "nsut@123",
    method="pbkdf2:sha256"
)

faculty_hash = generate_password_hash(
    "nsut@123",
    method="pbkdf2:sha256"
)

admin_hash = generate_password_hash(
    "admin123",
    method="pbkdf2:sha256"
)

# Create admin
cursor.execute("""
    INSERT IGNORE INTO user_account
    (username, password_hash, role)
    VALUES (%s, %s, %s)
""", ("admin", admin_hash, "admin"))

print("Admin account created...")

# Create student accounts
cursor.execute("SELECT roll_no FROM student")
students = cursor.fetchall()

student_accounts = [
    (roll_no, student_hash, "student", roll_no)
    for (roll_no,) in students
]

cursor.executemany("""
    INSERT IGNORE INTO user_account
    (username, password_hash, role, student_roll_no)
    VALUES (%s, %s, %s, %s)
""", student_accounts)

print(f"{len(student_accounts)} student accounts processed...")

# Create faculty accounts
cursor.execute("SELECT faculty_id, email FROM faculty")
faculty = cursor.fetchall()

faculty_accounts = [
    (email, faculty_hash, "faculty", faculty_id)
    for faculty_id, email in faculty if email
]

cursor.executemany("""
    INSERT IGNORE INTO user_account
    (username, password_hash, role, faculty_id)
    VALUES (%s, %s, %s, %s)
""", faculty_accounts)

db.commit()

print(f"{len(faculty_accounts)} faculty accounts processed...")
print("SUCCESS: Demo accounts created!")

cursor.close()
db.close()
