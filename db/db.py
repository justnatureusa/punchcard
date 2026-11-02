import sqlite3

from pathlib import Path

SOURCE = Path(__file__).parent
DB_PATH = SOURCE / "data.db"
MIGRATIONS = SOURCE / "migrations"


def connect(path=DB_PATH):
    # check_same_thread=False: the web server may open and use a connection
    # on different threads. Each request still gets its own connection.
    conn = sqlite3.connect(path, autocommit=False, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def migrate(conn: sqlite3.Connection):
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for path in sorted(MIGRATIONS.glob("*.sql")):
        version = int(path.name.split("_")[0])
        if version <= current:
            continue

        with conn:
            conn.executescript(path.read_text())
            conn.execute(f"PRAGMA user_version = {version}")


# employees

def create_employee(conn: sqlite3.Connection, eid: str, name: str, email: str | None, card_token: str):
    with conn:
        conn.execute(
            "INSERT INTO employees (eid, name, email, card_token) VALUES (?, ?, ?, ?)",
            (eid, name, email, card_token),
        )


def get_employee(conn: sqlite3.Connection, eid: str):
    return conn.execute("SELECT * FROM employees WHERE eid = ?", (eid,)).fetchone()


def get_employee_by_token(conn: sqlite3.Connection, card_token: str):
    return conn.execute("SELECT * FROM employees WHERE card_token = ?", (card_token,)).fetchone()


def list_employees(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM employees ORDER BY name").fetchall()


# punches

def add_punch(conn: sqlite3.Connection, eid: str, punch_type: str, ip_address: str | None, flagged: bool):
    with conn:
        conn.execute(
            "INSERT INTO punches (eid, punch_type, ip_address, flagged) VALUES (?, ?, ?, ?)",
            (eid, punch_type, ip_address, flagged),
        )


def add_manual_punch(conn: sqlite3.Connection, eid: str, punch_type: str, timestamp: str):
    """A punch a manager added by hand, like a forgotten clock-out."""
    with conn:
        conn.execute(
            "INSERT INTO punches (eid, punch_type, timestamp, edited_at) VALUES (?, ?, ?, datetime('now'))",
            (eid, punch_type, timestamp),
        )


def set_punch_time(conn: sqlite3.Connection, punch_id: int, timestamp: str):
    """Move a punch to a new time, keeping the time it was first recorded at."""
    with conn:
        conn.execute(
            """
            UPDATE punches
            SET original_timestamp = COALESCE(original_timestamp, timestamp),
                timestamp = ?,
                edited_at = datetime('now')
            WHERE id = ?
            """,
            (timestamp, punch_id),
        )


def get_punch(conn: sqlite3.Connection, punch_id: int):
    return conn.execute("SELECT * FROM punches WHERE id = ?", (punch_id,)).fetchone()


def employee_punches(conn: sqlite3.Connection, eid: str):
    """One employee's punches, oldest first."""
    return conn.execute(
        "SELECT * FROM punches WHERE eid = ? ORDER BY timestamp, id", (eid,)
    ).fetchall()


def last_punch(conn: sqlite3.Connection, eid: str):
    return conn.execute(
        "SELECT * FROM punches WHERE eid = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
        (eid,),
    ).fetchone()


def list_punches(conn: sqlite3.Connection):
    """Every punch, oldest first, with the employee's name."""
    return conn.execute(
        """
        SELECT punches.*, employees.name
        FROM punches
        JOIN employees ON employees.eid = punches.eid
        ORDER BY punches.timestamp, punches.id
        """
    ).fetchall()
