from functools import wraps
from contextlib import contextmanager
import os

import mysql.connector
from flask import Flask, jsonify, render_template, request, session
from dotenv import load_dotenv
from werkzeug.security import check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-demo-secret")


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "nsut_exam"),
    )


@contextmanager
def db_cursor(dictionary=True):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=dictionary)
    try:
        yield connection, cursor
    finally:
        cursor.close()
        connection.close()


def api_error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def login_required(*roles):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return api_error("Please log in first.", 401)
            if roles and session.get("role") not in roles:
                return api_error("You do not have permission for this action.", 403)
            return function(*args, **kwargs)
        return wrapper
    return decorator


def read_int(value, field_name, minimum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a whole number.")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}.")
    return number


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health():
    try:
        with db_cursor() as (_, cursor):
            cursor.execute("SELECT COUNT(*) AS total_students FROM student")
            row = cursor.fetchone()
        return jsonify({
            "status": "success",
            "database": "connected",
            "total_students": row["total_students"],
        })
    except mysql.connector.Error as error:
        return api_error(f"Database connection failed: {error}", 500)


@app.route("/api/branches", methods=["GET"])
def get_branches():
    try:
        with db_cursor() as (_, cursor):
            cursor.execute("SELECT branch_code, name FROM branch ORDER BY branch_code")
            rows = cursor.fetchall()
        return jsonify(rows)
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/faculty", methods=["GET"])
@login_required("admin")
def get_faculty():
    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                "SELECT faculty_id, name, branch_code, email FROM faculty ORDER BY faculty_id"
            )
            faculty = cursor.fetchall()
        return jsonify({"status": "success", "faculty": faculty})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/admin/student-seat", methods=["GET"])
@login_required("admin")
def admin_student_seat():
    roll_no = request.args.get("roll_no", "").strip().upper()
    if not roll_no:
        return api_error("roll_no is required.")
    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                "SELECT roll_no, name, branch_code, semester FROM student WHERE roll_no=%s",
                (roll_no,),
            )
            student = cursor.fetchone()
            if not student:
                return api_error("Student not found.", 404)
            cursor.execute(
                """SELECT es.exam_date, es.shift, s.subject_code, s.name AS subject_name,
                          r.room_name, a.seat_no
                   FROM exam e
                   JOIN exam_slot es ON es.slot_id=e.slot_id
                   JOIN subject s ON s.subject_code=e.subject_code
                   LEFT JOIN seat_allocation a
                     ON a.exam_id=e.exam_id AND a.roll_no=%s
                   LEFT JOIN room r ON r.room_id=a.room_id
                   WHERE s.branch_code=%s AND s.semester=%s
                   ORDER BY es.exam_date, es.shift""",
                (roll_no, student["branch_code"], student["semester"]),
            )
            exams = cursor.fetchall()
        return jsonify({"status": "success", "student": student, "exams": exams})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return api_error("Username and password are required.")

    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                """SELECT user_id, username, password_hash, role,
                          student_roll_no, faculty_id
                   FROM user_account WHERE username = %s""",
                (username,),
            )
            user = cursor.fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            return api_error("Invalid username or password.", 401)

        session.clear()
        session["user_id"] = user["user_id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["student_roll_no"] = user["student_roll_no"]
        session["faculty_id"] = user["faculty_id"]

        return jsonify({
            "status": "success",
            "message": "Login successful",
            "username": user["username"],
            "role": user["role"],
            "student_roll_no": user["student_roll_no"],
            "faculty_id": user["faculty_id"],
        })
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "success", "message": "Logged out successfully"})


@app.route("/api/me", methods=["GET"])
@login_required()
def current_user():
    return jsonify({
        "status": "success",
        "user_id": session["user_id"],
        "username": session["username"],
        "role": session["role"],
        "student_roll_no": session.get("student_roll_no"),
        "faculty_id": session.get("faculty_id"),
    })


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/stats", methods=["GET"])
@login_required("admin")
def dashboard_stats():
    try:
        with db_cursor() as (_, cursor):
            result = {}
            for table, key in [
                ("student", "students"),
                ("faculty", "faculty"),
                ("subject", "subjects"),
                ("exam", "exams"),
                ("room", "rooms"),
                ("seat_allocation", "seats_allocated"),
                ("invigilation", "duties"),
            ]:
                cursor.execute(f"SELECT COUNT(*) AS total FROM {table}")
                result[key] = cursor.fetchone()["total"]

            cursor.execute("SELECT COALESCE(SUM(capacity), 0) AS total FROM room")
            result["seat_capacity"] = cursor.fetchone()["total"]

        return jsonify({"status": "success", **result})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


# ---------------------------------------------------------------------------
# Rooms: list, add, edit, delete
# ---------------------------------------------------------------------------

@app.route("/api/rooms", methods=["GET"])
@login_required("admin")
def get_rooms():
    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                "SELECT room_id, room_name, capacity FROM room ORDER BY room_id"
            )
            rooms = cursor.fetchall()
        return jsonify({"status": "success", "rooms": rooms})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/rooms", methods=["POST"])
@login_required("admin")
def add_room():
    data = request.get_json(silent=True) or {}
    room_name = str(data.get("room_name", "")).strip()
    try:
        capacity = read_int(data.get("capacity"), "Capacity", 1)
    except ValueError as error:
        return api_error(str(error))

    if not room_name or len(room_name) > 30:
        return api_error("Room name is required and must be at most 30 characters.")

    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute(
                "INSERT INTO room (room_name, capacity) VALUES (%s, %s)",
                (room_name, capacity),
            )
            connection.commit()
            room_id = cursor.lastrowid
        return jsonify({
            "status": "success",
            "message": "Room added",
            "room": {"room_id": room_id, "room_name": room_name, "capacity": capacity},
        }), 201
    except mysql.connector.IntegrityError:
        return api_error("A room with that name already exists.", 409)
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/rooms/<int:room_id>", methods=["PUT"])
@login_required("admin")
def update_room(room_id):
    data = request.get_json(silent=True) or {}
    room_name = str(data.get("room_name", "")).strip()
    try:
        capacity = read_int(data.get("capacity"), "Capacity", 1)
    except ValueError as error:
        return api_error(str(error))

    if not room_name or len(room_name) > 30:
        return api_error("Room name is required and must be at most 30 characters.")

    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute(
                "UPDATE room SET room_name=%s, capacity=%s WHERE room_id=%s",
                (room_name, capacity, room_id),
            )
            changed = cursor.rowcount
            connection.commit()
        if changed == 0:
            return api_error("Room not found or no values changed.", 404)
        return jsonify({"status": "success", "message": "Room updated"})
    except mysql.connector.IntegrityError:
        return api_error("A room with that name already exists.", 409)
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/rooms/<int:room_id>", methods=["DELETE"])
@login_required("admin")
def delete_room(room_id):
    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute("DELETE FROM room WHERE room_id=%s", (room_id,))
            deleted = cursor.rowcount
            connection.commit()
        if not deleted:
            return api_error("Room not found.", 404)
        return jsonify({"status": "success", "message": "Room deleted"})
    except mysql.connector.IntegrityError:
        return api_error(
            "This room is linked to seating or invigilation records. "
            "Remove those records before deleting the room.",
            409,
        )
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


# ---------------------------------------------------------------------------
# Subjects and exam scheduling
# ---------------------------------------------------------------------------

@app.route("/api/subjects", methods=["GET"])
@login_required("admin")
def get_subjects():
    branch_code = request.args.get("branch_code", "").strip()
    semester = request.args.get("semester", type=int)
    if not branch_code or semester is None:
        return api_error("branch_code and semester are required.")

    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                """SELECT subject_code, name, branch_code, semester, credits
                   FROM subject
                   WHERE branch_code=%s AND semester=%s
                   ORDER BY subject_code""",
                (branch_code, semester),
            )
            subjects = cursor.fetchall()
        return jsonify({"status": "success", "subjects": subjects})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/exams", methods=["GET"])
@login_required("admin")
def get_exams():
    semester = request.args.get("semester", type=int)
    query = """
        SELECT e.exam_id, e.subject_code, e.slot_id, e.slot_label,
               es.exam_date, es.shift, s.name AS subject_name,
               s.branch_code, s.semester
        FROM exam e
        JOIN exam_slot es ON es.slot_id=e.slot_id
        JOIN subject s ON s.subject_code=e.subject_code
    """
    params = ()
    if semester is not None:
        query += " WHERE s.semester=%s"
        params = (semester,)
    query += " ORDER BY es.exam_date, es.shift, s.branch_code, s.semester"

    try:
        with db_cursor() as (_, cursor):
            cursor.execute(query, params)
            exams = cursor.fetchall()
        return jsonify({"status": "success", "exams": exams})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/exams", methods=["POST"])
@login_required("admin")
def add_exam():
    data = request.get_json(silent=True) or {}
    subject_code = str(data.get("subject_code", "")).strip()
    branch_code = str(data.get("branch_code", "")).strip()
    shift = str(data.get("shift", "")).strip().upper()
    slot_label = str(data.get("slot_label", "")).strip()
    exam_date = str(data.get("exam_date", "")).strip()

    try:
        semester = read_int(data.get("semester"), "Semester", 1)
    except ValueError as error:
        return api_error(str(error))

    if semester > 8:
        return api_error("Semester must be between 1 and 8.")
    if not subject_code or not branch_code or not exam_date or not slot_label:
        return api_error("Subject, branch, date and slot label are required.")
    if shift not in ("FN", "AN"):
        return api_error("Shift must be FN or AN.")

    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute(
                """SELECT subject_code FROM subject
                   WHERE subject_code=%s AND branch_code=%s AND semester=%s""",
                (subject_code, branch_code, semester),
            )
            if not cursor.fetchone():
                return api_error("The subject does not belong to the selected branch and semester.", 404)

            cursor.execute(
                """SELECT e.exam_id
                   FROM exam e
                   JOIN exam_slot es ON es.slot_id=e.slot_id
                   JOIN subject s ON s.subject_code=e.subject_code
                   WHERE es.exam_date=%s AND es.shift=%s
                     AND s.branch_code=%s AND s.semester=%s""",
                (exam_date, shift, branch_code, semester),
            )
            if cursor.fetchone():
                return api_error(
                    "Clash: this branch and semester already has an exam in that slot.",
                    409,
                )

            cursor.execute("SELECT exam_id FROM exam WHERE subject_code=%s", (subject_code,))
            if cursor.fetchone():
                return api_error("This subject already has an exam scheduled.", 409)

            cursor.execute(
                "SELECT slot_id FROM exam_slot WHERE exam_date=%s AND shift=%s",
                (exam_date, shift),
            )
            slot = cursor.fetchone()
            if slot:
                slot_id = slot[0]
            else:
                cursor.execute(
                    "INSERT INTO exam_slot (exam_date, shift) VALUES (%s, %s)",
                    (exam_date, shift),
                )
                slot_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO exam (subject_code, slot_id, slot_label) VALUES (%s, %s, %s)",
                (subject_code, slot_id, slot_label),
            )
            exam_id = cursor.lastrowid
            connection.commit()

        return jsonify({
            "status": "success",
            "message": "Exam scheduled",
            "exam_id": exam_id,
            "slot_id": slot_id,
        }), 201
    except mysql.connector.IntegrityError as error:
        return api_error(f"Could not schedule exam: {error}", 409)
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/exams/<int:exam_id>", methods=["DELETE"])
@login_required("admin")
def delete_exam(exam_id):
    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute("DELETE FROM seat_allocation WHERE exam_id=%s", (exam_id,))
            cursor.execute("DELETE FROM exam WHERE exam_id=%s", (exam_id,))
            deleted = cursor.rowcount
            connection.commit()
        if not deleted:
            return api_error("Exam not found.", 404)
        return jsonify({"status": "success", "message": "Exam deleted"})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/exams/semester/<int:semester>", methods=["DELETE"])
@login_required("admin")
def clear_semester_exams(semester):
    if semester < 1 or semester > 8:
        return api_error("Semester must be between 1 and 8.")
    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute(
                """SELECT e.exam_id FROM exam e
                   JOIN subject s ON s.subject_code=e.subject_code
                   WHERE s.semester=%s""",
                (semester,),
            )
            ids = [row[0] for row in cursor.fetchall()]
            if ids:
                marks = ",".join(["%s"] * len(ids))
                cursor.execute(
                    f"DELETE FROM seat_allocation WHERE exam_id IN ({marks})", tuple(ids)
                )
                cursor.execute(
                    f"DELETE FROM exam WHERE exam_id IN ({marks})", tuple(ids)
                )
            connection.commit()
        return jsonify({"status": "success", "deleted_exams": len(ids)})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/slots", methods=["GET"])
@login_required("admin")
def get_slots():
    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                """SELECT DISTINCT es.slot_id, es.exam_date, es.shift
                   FROM exam_slot es JOIN exam e ON e.slot_id=es.slot_id
                   ORDER BY es.exam_date, es.shift"""
            )
            slots = cursor.fetchall()
        return jsonify({"status": "success", "slots": slots})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


# ---------------------------------------------------------------------------
# Seat allocation and automatic invigilator assignment
# ---------------------------------------------------------------------------

@app.route("/api/allocate", methods=["POST"])
@login_required("admin")
def allocate_seats():
    data = request.get_json(silent=True) or {}
    exam_date = str(data.get("exam_date", "")).strip()
    shift = str(data.get("shift", "")).strip().upper()
    if not exam_date or shift not in ("FN", "AN"):
        return api_error("A valid exam_date and shift (FN/AN) are required.")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()

        cursor.execute(
            "SELECT slot_id FROM exam_slot WHERE exam_date=%s AND shift=%s",
            (exam_date, shift),
        )
        slot = cursor.fetchone()
        if not slot:
            connection.rollback()
            return api_error("No exam slot exists for that date and shift.", 404)
        slot_id = slot["slot_id"]

        cursor.execute(
            """SELECT e.exam_id, s.branch_code, s.semester, s.subject_code
               FROM exam e JOIN subject s ON s.subject_code=e.subject_code
               WHERE e.slot_id=%s ORDER BY s.branch_code, s.semester""",
            (slot_id,),
        )
        exams = cursor.fetchall()
        if not exams:
            connection.rollback()
            return api_error("There are no exams in this slot.", 404)

        # Interleave students from the exams, matching the project's seating logic.
        student_lists = []
        for exam in exams:
            cursor.execute(
                """SELECT roll_no FROM student
                   WHERE branch_code=%s AND semester=%s ORDER BY roll_no""",
                (exam["branch_code"], exam["semester"]),
            )
            student_lists.append([
                {"exam_id": exam["exam_id"], "roll_no": row["roll_no"]}
                for row in cursor.fetchall()
            ])

        mixed_students = []
        longest = max((len(items) for items in student_lists), default=0)
        for index in range(longest):
            for items in student_lists:
                if index < len(items):
                    mixed_students.append(items[index])

        cursor.execute(
            "SELECT room_id, room_name, capacity FROM room ORDER BY capacity DESC, room_id"
        )
        rooms = cursor.fetchall()
        total_capacity = sum(room["capacity"] for room in rooms)
        if total_capacity < len(mixed_students):
            connection.rollback()
            return api_error(
                f"Insufficient room capacity: {len(mixed_students)} students need seats, "
                f"but all rooms together hold {total_capacity}.",
                409,
            )

        # Determine how many rooms will be used before changing existing allocations.
        used_rooms = []
        remaining = len(mixed_students)
        for room in rooms:
            if remaining <= 0:
                break
            used_rooms.append(room)
            remaining -= room["capacity"]

        cursor.execute("SELECT faculty_id FROM faculty ORDER BY faculty_id")
        faculty_ids = [row["faculty_id"] for row in cursor.fetchall()]
        needed_faculty = 2 * len(used_rooms)
        if len(faculty_ids) < needed_faculty:
            connection.rollback()
            return api_error(
                f"Not enough faculty for automatic assignment: {needed_faculty} "
                f"are needed, but only {len(faculty_ids)} exist.",
                409,
            )

        exam_ids = [exam["exam_id"] for exam in exams]
        marks = ",".join(["%s"] * len(exam_ids))
        cursor.execute(
            f"DELETE FROM seat_allocation WHERE exam_id IN ({marks})",
            tuple(exam_ids),
        )
        cursor.execute("DELETE FROM invigilation WHERE slot_id=%s", (slot_id,))

        student_index = 0
        faculty_index = 0
        allocated_count = 0

        for room in used_rooms:
            room_students = mixed_students[
                student_index:student_index + room["capacity"]
            ]
            for seat_number, student in enumerate(room_students, start=1):
                cursor.execute(
                    """INSERT INTO seat_allocation
                       (exam_id, roll_no, room_id, seat_no)
                       VALUES (%s, %s, %s, %s)""",
                    (
                        student["exam_id"],
                        student["roll_no"],
                        room["room_id"],
                        seat_number,
                    ),
                )
                allocated_count += 1

            student_index += len(room_students)

            for _ in range(2):
                cursor.execute(
                    """INSERT INTO invigilation (slot_id, room_id, faculty_id)
                       VALUES (%s, %s, %s)""",
                    (slot_id, room["room_id"], faculty_ids[faculty_index]),
                )
                faculty_index += 1

        connection.commit()
        return jsonify({
            "status": "success",
            "message": "Seats and invigilators allocated",
            "exam_date": exam_date,
            "shift": shift,
            "total_exams": len(exams),
            "students_allocated": allocated_count,
            "rooms_used": len(used_rooms),
            "invigilators_assigned": needed_faculty,
        })
    except mysql.connector.Error as error:
        connection.rollback()
        return api_error(str(error), 500)
    finally:
        cursor.close()
        connection.close()


@app.route("/api/allocations", methods=["GET"])
@login_required("admin")
def get_allocations():
    exam_date = request.args.get("exam_date", "").strip()
    shift = request.args.get("shift", "").strip().upper()
    if not exam_date or shift not in ("FN", "AN"):
        return api_error("exam_date and shift (FN/AN) are required.")

    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                """SELECT a.exam_id, a.roll_no, st.name AS student_name,
                          a.room_id, r.room_name, a.seat_no,
                          s.subject_code, s.name AS subject_name
                   FROM seat_allocation a
                   JOIN exam e ON e.exam_id=a.exam_id
                   JOIN exam_slot es ON es.slot_id=e.slot_id
                   JOIN student st ON st.roll_no=a.roll_no
                   JOIN room r ON r.room_id=a.room_id
                   JOIN subject s ON s.subject_code=e.subject_code
                   WHERE es.exam_date=%s AND es.shift=%s
                   ORDER BY r.room_name, a.seat_no""",
                (exam_date, shift),
            )
            allocations = cursor.fetchall()
        return jsonify({"status": "success", "allocations": allocations})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


# ---------------------------------------------------------------------------
# Manual invigilation management
# ---------------------------------------------------------------------------

@app.route("/api/invigilation", methods=["GET"])
@login_required("admin")
def get_invigilation():
    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                """SELECT i.slot_id, es.exam_date, es.shift, i.room_id,
                          r.room_name, i.faculty_id, f.name AS faculty_name
                   FROM invigilation i
                   JOIN exam_slot es ON es.slot_id=i.slot_id
                   JOIN room r ON r.room_id=i.room_id
                   JOIN faculty f ON f.faculty_id=i.faculty_id
                   ORDER BY es.exam_date, es.shift, r.room_name, f.name"""
            )
            duties = cursor.fetchall()
        return jsonify({"status": "success", "duties": duties})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route("/api/invigilation", methods=["POST"])
@login_required("admin")
def add_invigilation():
    data = request.get_json(silent=True) or {}
    try:
        slot_id = read_int(data.get("slot_id"), "slot_id", 1)
        room_id = read_int(data.get("room_id"), "room_id", 1)
        faculty_id = read_int(data.get("faculty_id"), "faculty_id", 1)
    except ValueError as error:
        return api_error(str(error))

    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute(
                "SELECT slot_id FROM exam_slot WHERE slot_id=%s", (slot_id,)
            )
            if not cursor.fetchone():
                return api_error("Exam slot not found.", 404)
            cursor.execute("SELECT room_id FROM room WHERE room_id=%s", (room_id,))
            if not cursor.fetchone():
                return api_error("Room not found.", 404)
            cursor.execute(
                "SELECT faculty_id FROM faculty WHERE faculty_id=%s", (faculty_id,)
            )
            if not cursor.fetchone():
                return api_error("Faculty member not found.", 404)

            cursor.execute(
                """SELECT faculty_id FROM invigilation
                   WHERE slot_id=%s AND faculty_id=%s""",
                (slot_id, faculty_id),
            )
            if cursor.fetchone():
                return api_error("Clash: this faculty member already has a duty in this slot.", 409)

            cursor.execute(
                """INSERT INTO invigilation (slot_id, room_id, faculty_id)
                   VALUES (%s, %s, %s)""",
                (slot_id, room_id, faculty_id),
            )
            connection.commit()
        return jsonify({"status": "success", "message": "Invigilator assigned"}), 201
    except mysql.connector.IntegrityError as error:
        return api_error(f"Assignment conflicts with an existing record: {error}", 409)
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.route(
    "/api/invigilation/<int:slot_id>/<int:room_id>/<int:faculty_id>",
    methods=["DELETE"],
)
@login_required("admin")
def delete_invigilation(slot_id, room_id, faculty_id):
    try:
        with db_cursor(dictionary=False) as (connection, cursor):
            cursor.execute(
                """DELETE FROM invigilation
                   WHERE slot_id=%s AND room_id=%s AND faculty_id=%s""",
                (slot_id, room_id, faculty_id),
            )
            deleted = cursor.rowcount
            connection.commit()
        if not deleted:
            return api_error("Duty assignment not found.", 404)
        return jsonify({"status": "success", "message": "Duty assignment removed"})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


# ---------------------------------------------------------------------------
# Student portal: only the logged-in student's own timetable and seats
# ---------------------------------------------------------------------------

@app.route("/api/student/me", methods=["GET"])
@login_required("student")
def student_portal():
    roll_no = session.get("student_roll_no")
    if not roll_no:
        return api_error("Student account is not linked to a roll number.", 403)

    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                """SELECT roll_no, name, branch_code, semester, email
                   FROM student WHERE roll_no=%s""",
                (roll_no,),
            )
            student = cursor.fetchone()
            if not student:
                return api_error("Student record not found.", 404)

            cursor.execute(
                """SELECT es.exam_date, es.shift, e.exam_id, e.slot_label,
                          s.subject_code, s.name AS subject_name,
                          r.room_id, r.room_name, a.seat_no
                   FROM exam e
                   JOIN exam_slot es ON es.slot_id=e.slot_id
                   JOIN subject s ON s.subject_code=e.subject_code
                   LEFT JOIN seat_allocation a
                     ON a.exam_id=e.exam_id AND a.roll_no=%s
                   LEFT JOIN room r ON r.room_id=a.room_id
                   WHERE s.branch_code=%s AND s.semester=%s
                   ORDER BY es.exam_date, es.shift""",
                (roll_no, student["branch_code"], student["semester"]),
            )
            exams = cursor.fetchall()

        return jsonify({"status": "success", "student": student, "exams": exams})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


# ---------------------------------------------------------------------------
# Faculty portal: own duties and room seating lists
# ---------------------------------------------------------------------------

@app.route("/api/faculty/me/duties", methods=["GET"])
@login_required("faculty")
def faculty_duties():
    faculty_id = session.get("faculty_id")
    if not faculty_id:
        return api_error("Faculty account is not linked to a faculty record.", 403)

    try:
        with db_cursor() as (_, cursor):
            cursor.execute(
                """SELECT i.slot_id, es.exam_date, es.shift, i.room_id,
                          r.room_name, r.capacity
                   FROM invigilation i
                   JOIN exam_slot es ON es.slot_id=i.slot_id
                   JOIN room r ON r.room_id=i.room_id
                   WHERE i.faculty_id=%s
                   ORDER BY es.exam_date, es.shift, r.room_name""",
                (faculty_id,),
            )
            duties = cursor.fetchall()

            for duty in duties:
                cursor.execute(
                    """SELECT a.seat_no, a.roll_no, st.name AS student_name,
                              s.subject_code, s.name AS subject_name
                       FROM seat_allocation a
                       JOIN exam e ON e.exam_id=a.exam_id
                       JOIN student st ON st.roll_no=a.roll_no
                       JOIN subject s ON s.subject_code=e.subject_code
                       WHERE e.slot_id=%s AND a.room_id=%s
                       ORDER BY a.seat_no""",
                    (duty["slot_id"], duty["room_id"]),
                )
                duty["students"] = cursor.fetchall()

        return jsonify({"status": "success", "duties": duties})
    except mysql.connector.Error as error:
        return api_error(str(error), 500)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return api_error("API endpoint not found.", 404)
    return "Page not found", 404


if __name__ == "__main__":
    app.run(debug=True)
