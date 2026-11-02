import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import db

# A clock-in older than this is treated as a forgotten clock-out,
# so the employee can still clock in for their next shift.
MAX_SHIFT = timedelta(hours=16)


class PunchError(Exception):
    """A scan that breaks the in/out rules."""


def punch(conn, token: str, direction: str, ip_address: str | None = None,
          shop_network: str | None = None, now: datetime | None = None):
    if direction not in ("in", "out"):
        raise PunchError("Choose in or out first")

    employee = db.get_employee_by_token(conn, token)
    if employee is None:
        raise PunchError("Unknown card")

    status = current_status(conn, employee["eid"], now or utc_now())
    if direction == status:
        raise PunchError(f"{employee['name']} is already clocked {direction}")

    flagged = not on_shop_network(ip_address, shop_network)
    db.add_punch(conn, employee["eid"], direction, ip_address, flagged)
    return employee


def current_status(conn, eid: str, now: datetime) -> str:
    last = db.last_punch(conn, eid)
    if last is None or last["punch_type"] == "out":
        return "out"
    if now - parse_utc(last["timestamp"]) > MAX_SHIFT:
        return "out"
    return "in"


def edit_shift(conn, in_id: int, clock_in: datetime, clock_out: datetime | None,
               now: datetime | None = None):
    """Change a shift's times. A missing clock-out can be filled in."""
    first = db.get_punch(conn, in_id)
    if first is None or first["punch_type"] != "in":
        raise PunchError("No such shift")

    # Find this shift among the employee's punches, and the punches around it.
    punches = db.employee_punches(conn, first["eid"])
    i = [p["id"] for p in punches].index(in_id)
    before, after = punches[:i], punches[i + 1:]
    out = after.pop(0) if after and after[0]["punch_type"] == "out" else None
    previous = before[-1] if before else None
    following = after[0] if after else None
    end = clock_out or clock_in

    if out is not None and clock_out is None:
        raise PunchError("Enter a clock-out time")
    if clock_out is not None and clock_out <= clock_in:
        raise PunchError("Clock-out has to be after clock-in")
    if end > (now or utc_now()):
        raise PunchError("Times can't be in the future")
    if previous is not None and clock_in <= parse_utc(previous["timestamp"]):
        raise PunchError("That overlaps the shift before it")
    if following is not None and end >= parse_utc(following["timestamp"]):
        raise PunchError("That overlaps the shift after it")

    move_punch(conn, first, clock_in)
    if out is not None:
        move_punch(conn, out, clock_out)
    elif clock_out is not None:
        db.add_manual_punch(conn, first["eid"], "out", to_db(clock_out))


def move_punch(conn, punch, time: datetime):
    # The edit form works in whole minutes, so ignore a change in seconds only.
    if to_db(time)[:16] != punch["timestamp"][:16]:
        db.set_punch_time(conn, punch["id"], to_db(time))


def on_shop_network(ip_address: str | None, shop_network: str | None) -> bool:
    if shop_network is None:
        return True
    try:
        return ipaddress.ip_address(ip_address) in ipaddress.ip_network(shop_network)
    except ValueError:
        return False


# report

@dataclass
class Shift:
    id: int  # the clock-in punch's id
    eid: str
    name: str
    clock_in: datetime
    clock_out: datetime | None
    flagged: bool
    edited: bool

    @property
    def hours(self) -> float | None:
        if self.clock_out is None:
            return None
        return (self.clock_out - self.clock_in).total_seconds() / 3600


def shifts(punches) -> list[Shift]:
    """Pair each clock-in with the clock-out after it. Expects punches oldest first."""
    result = []
    open_shifts = {}

    for p in punches:
        time = parse_utc(p["timestamp"])
        flagged = bool(p["flagged"])
        edited = p["edited_at"] is not None
        if p["punch_type"] == "in":
            shift = Shift(p["id"], p["eid"], p["name"], time, None, flagged, edited)
            open_shifts[p["eid"]] = shift
            result.append(shift)
        else:
            shift = open_shifts.pop(p["eid"], None)
            if shift is not None:
                shift.clock_out = time
                shift.flagged = shift.flagged or flagged
                shift.edited = shift.edited or edited

    return result


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(text: str) -> datetime:
    """SQLite's datetime('now') is UTC without a timezone marker."""
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def to_db(time: datetime) -> str:
    """The same format as SQLite's datetime('now'), so times sort correctly."""
    return time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
