import csv
import io
import ipaddress
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import cards
import db
import tracker

# settings, read from environment variables
DATABASE = os.environ.get("DATABASE", db.DB_PATH)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
SHOP_NETWORK = os.environ.get("SHOP_NETWORK") or None  # e.g. 192.168.1.0/24
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "America/Los_Angeles"))

PAGE = Path(__file__).parent / "static" / "index.html"

if SHOP_NETWORK:
    ipaddress.ip_network(SHOP_NETWORK)  # stop at startup if it has a typo


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect(DATABASE)
    db.migrate(conn)
    conn.close()
    yield


app = FastAPI(lifespan=lifespan)


# a database connection for each request

def get_conn():
    conn = db.connect(DATABASE)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


# employee and report endpoints need the admin password in an X-Admin-Password header

def require_admin(x_admin_password: Annotated[str, Header()] = ""):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Set ADMIN_PASSWORD on the server first")
    if not secrets.compare_digest(x_admin_password.encode(), ADMIN_PASSWORD.encode()):
        raise HTTPException(401, "Wrong password")


ADMIN_ONLY = [Depends(require_admin)]


@app.get("/")
def page():
    return FileResponse(PAGE)


# clocking in and out

class PunchRequest(BaseModel):
    token: str
    direction: Literal["in", "out"]


@app.post("/api/punch")
def punch(body: PunchRequest, request: Request, conn: Conn):
    ip_address = request.client.host if request.client else None
    try:
        employee = tracker.punch(conn, body.token, body.direction, ip_address, SHOP_NETWORK)
    except tracker.PunchError as error:
        raise HTTPException(400, str(error))

    return {"name": employee["name"], "direction": body.direction}


# employees and cards

class NewEmployee(BaseModel):
    eid: str
    name: str
    email: str = ""


@app.get("/api/employees", dependencies=ADMIN_ONLY)
def list_employees(conn: Conn):
    return [
        {"eid": e["eid"], "name": e["name"], "email": e["email"]}
        for e in db.list_employees(conn)
    ]


@app.post("/api/employees", status_code=201, dependencies=ADMIN_ONLY)
def add_employee(body: NewEmployee, conn: Conn):
    eid, name, email = body.eid.strip(), body.name.strip(), body.email.strip() or None
    if not eid or not name:
        raise HTTPException(400, "Employee ID and name are required")

    try:
        db.create_employee(conn, eid, name, email, cards.new_token())
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Employee ID {eid} already exists")

    return {"eid": eid, "name": name, "email": email}


@app.get("/api/employees/{eid}/card.png", dependencies=ADMIN_ONLY)
def card_image(eid: str, conn: Conn):
    employee = db.get_employee(conn, eid)
    if employee is None:
        raise HTTPException(404, "No such employee")
    return Response(cards.qr_png(employee["card_token"]), media_type="image/png")


# report

def local(time, format="%Y-%m-%d %I:%M %p"):
    if time is None:
        return ""
    return time.astimezone(TIMEZONE).strftime(format)


def for_input(time):
    """The format an <input type="datetime-local"> uses."""
    return local(time, "%Y-%m-%dT%H:%M")


def report_rows(conn: sqlite3.Connection):
    """Every shift, oldest first, ready to show or export."""
    stale_before = tracker.utc_now() - tracker.MAX_SHIFT
    return [
        {
            "id": shift.id,
            "eid": shift.eid,
            "name": shift.name,
            "clock_in": local(shift.clock_in),
            "clock_out": local(shift.clock_out),
            "clock_in_input": for_input(shift.clock_in),
            "clock_out_input": for_input(shift.clock_out),
            "hours": round(shift.hours, 2) if shift.hours is not None else None,
            "missing_clock_out": shift.clock_out is None and shift.clock_in < stale_before,
            "flagged": shift.flagged,
            "edited": shift.edited,
        }
        for shift in tracker.shifts(db.list_punches(conn))
    ]


@app.get("/api/report", dependencies=ADMIN_ONLY)
def report(conn: Conn):
    return list(reversed(report_rows(conn)))  # newest first


class ShiftTimes(BaseModel):
    clock_in: datetime  # local time, like 2026-11-02T09:00
    clock_out: datetime | None = None


@app.put("/api/shifts/{shift_id}", dependencies=ADMIN_ONLY)
def edit_shift(shift_id: int, body: ShiftTimes, conn: Conn):
    clock_in = body.clock_in.replace(tzinfo=TIMEZONE)
    clock_out = body.clock_out.replace(tzinfo=TIMEZONE) if body.clock_out else None
    try:
        tracker.edit_shift(conn, shift_id, clock_in, clock_out)
    except tracker.PunchError as error:
        raise HTTPException(400, str(error))

    return {"ok": True}


@app.get("/api/report.csv", dependencies=ADMIN_ONLY)
def report_csv(conn: Conn):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["employee_id", "name", "clock_in", "clock_out", "hours", "flagged", "edited"])

    for row in report_rows(conn):
        hours = f"{row['hours']:.2f}" if row["hours"] is not None else ""
        flagged = "yes" if row["flagged"] else ""
        edited = "yes" if row["edited"] else ""
        writer.writerow([row["eid"], row["name"], row["clock_in"], row["clock_out"], hours, flagged, edited])

    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="punchcard.csv"'},
    )
