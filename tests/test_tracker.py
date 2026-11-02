from datetime import timedelta

import pytest

import db
import tracker


@pytest.fixture
def conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    db.create_employee(conn, "E1", "Mia", None, "mia-card")
    return conn


def punch_types(conn):
    return [p["punch_type"] for p in db.list_punches(conn)]


def test_clock_in_then_out(conn):
    tracker.punch(conn, "mia-card", "in")
    tracker.punch(conn, "mia-card", "out")
    assert punch_types(conn) == ["in", "out"]


def test_clock_in_again_after_clocking_out(conn):
    tracker.punch(conn, "mia-card", "in")
    tracker.punch(conn, "mia-card", "out")
    tracker.punch(conn, "mia-card", "in")
    assert punch_types(conn) == ["in", "out", "in"]


def test_cannot_clock_out_before_clocking_in(conn):
    with pytest.raises(tracker.PunchError, match="already clocked out"):
        tracker.punch(conn, "mia-card", "out")


def test_cannot_clock_in_twice(conn):
    tracker.punch(conn, "mia-card", "in")
    with pytest.raises(tracker.PunchError, match="already clocked in"):
        tracker.punch(conn, "mia-card", "in")


def test_cannot_clock_out_twice(conn):
    tracker.punch(conn, "mia-card", "in")
    tracker.punch(conn, "mia-card", "out")
    with pytest.raises(tracker.PunchError, match="already clocked out"):
        tracker.punch(conn, "mia-card", "out")


def test_unknown_card(conn):
    with pytest.raises(tracker.PunchError, match="Unknown card"):
        tracker.punch(conn, "not-a-card", "in")


def test_forgotten_clock_out_still_lets_you_clock_in_next_day(conn):
    tracker.punch(conn, "mia-card", "in")
    tomorrow = tracker.utc_now() + timedelta(hours=20)
    tracker.punch(conn, "mia-card", "in", now=tomorrow)
    assert punch_types(conn) == ["in", "in"]


def test_punch_outside_shop_network_is_flagged(conn):
    tracker.punch(conn, "mia-card", "in", "192.168.1.20", shop_network="192.168.1.0/24")
    tracker.punch(conn, "mia-card", "out", "8.8.8.8", shop_network="192.168.1.0/24")
    flags = [p["flagged"] for p in db.list_punches(conn)]
    assert flags == [0, 1]


def test_shifts_pair_clock_in_with_clock_out(conn):
    with conn:
        conn.executemany(
            "INSERT INTO punches (eid, punch_type, timestamp) VALUES ('E1', ?, ?)",
            [
                ("in", "2026-11-02 16:00:00"),
                ("out", "2026-11-03 00:30:00"),
                ("in", "2026-11-03 16:00:00"),
            ],
        )

    first, second = tracker.shifts(db.list_punches(conn))
    assert first.name == "Mia"
    assert first.hours == 8.5
    assert second.clock_out is None
    assert second.hours is None


# editing shifts

def at(text):
    return tracker.parse_utc(text)


def add_punches(conn, *punches):
    with conn:
        conn.executemany(
            "INSERT INTO punches (eid, punch_type, timestamp) VALUES ('E1', ?, ?)", punches
        )
    return [p["id"] for p in db.employee_punches(conn, "E1")]


def test_edit_shift_moves_both_times_and_keeps_the_originals(conn):
    in_id, out_id = add_punches(conn, ("in", "2026-10-12 16:00:00"), ("out", "2026-10-13 00:00:00"))

    tracker.edit_shift(conn, in_id, at("2026-10-12 15:30:00"), at("2026-10-13 00:15:00"))

    clock_in, clock_out = db.get_punch(conn, in_id), db.get_punch(conn, out_id)
    assert clock_in["timestamp"] == "2026-10-12 15:30:00"
    assert clock_in["original_timestamp"] == "2026-10-12 16:00:00"
    assert clock_out["timestamp"] == "2026-10-13 00:15:00"
    assert tracker.shifts(db.list_punches(conn))[0].edited


def test_unchanged_time_is_not_marked_edited(conn):
    in_id, out_id = add_punches(conn, ("in", "2026-10-12 16:00:00"), ("out", "2026-10-13 00:00:00"))

    tracker.edit_shift(conn, in_id, at("2026-10-12 16:00:00"), at("2026-10-13 01:00:00"))

    assert db.get_punch(conn, in_id)["edited_at"] is None
    assert db.get_punch(conn, out_id)["edited_at"] is not None


def test_fill_in_a_missing_clock_out(conn):
    [in_id] = add_punches(conn, ("in", "2026-10-12 16:00:00"))

    tracker.edit_shift(conn, in_id, at("2026-10-12 16:00:00"), at("2026-10-13 00:00:00"))

    [shift] = tracker.shifts(db.list_punches(conn))
    assert shift.hours == 8


def test_clock_out_must_be_after_clock_in(conn):
    in_id, _ = add_punches(conn, ("in", "2026-10-12 16:00:00"), ("out", "2026-10-13 00:00:00"))
    with pytest.raises(tracker.PunchError, match="after clock-in"):
        tracker.edit_shift(conn, in_id, at("2026-10-12 16:00:00"), at("2026-10-12 15:00:00"))


def test_cannot_remove_a_clock_out(conn):
    in_id, _ = add_punches(conn, ("in", "2026-10-12 16:00:00"), ("out", "2026-10-13 00:00:00"))
    with pytest.raises(tracker.PunchError, match="Enter a clock-out"):
        tracker.edit_shift(conn, in_id, at("2026-10-12 16:00:00"), None)


def test_cannot_overlap_the_next_shift(conn):
    in_id, *_ = add_punches(
        conn,
        ("in", "2026-10-12 16:00:00"),
        ("out", "2026-10-12 20:00:00"),
        ("in", "2026-10-12 21:00:00"),
        ("out", "2026-10-12 23:00:00"),
    )
    with pytest.raises(tracker.PunchError, match="shift after"):
        tracker.edit_shift(conn, in_id, at("2026-10-12 16:00:00"), at("2026-10-12 22:00:00"))


def test_cannot_overlap_the_previous_shift(conn):
    *_, in_id, _ = add_punches(
        conn,
        ("in", "2026-10-12 16:00:00"),
        ("out", "2026-10-12 20:00:00"),
        ("in", "2026-10-12 21:00:00"),
        ("out", "2026-10-12 23:00:00"),
    )
    with pytest.raises(tracker.PunchError, match="shift before"):
        tracker.edit_shift(conn, in_id, at("2026-10-12 19:00:00"), at("2026-10-12 23:00:00"))


def test_cannot_edit_into_the_future(conn):
    in_id, _ = add_punches(conn, ("in", "2026-10-12 16:00:00"), ("out", "2026-10-13 00:00:00"))
    with pytest.raises(tracker.PunchError, match="future"):
        tracker.edit_shift(conn, in_id, at("2026-10-12 16:00:00"), at("2026-10-13 00:00:00"),
                           now=at("2026-10-12 23:00:00"))
