CREATE TABLE employees (
    eid        TEXT NOT NULL PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT,
    card_token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE punches (
    id         INTEGER PRIMARY KEY,
    eid        TEXT NOT NULL REFERENCES employees(eid) ON UPDATE CASCADE,
    punch_type TEXT NOT NULL CHECK (punch_type IN ('in', 'out')),
    timestamp  TEXT NOT NULL DEFAULT (datetime('now')),  -- UTC
    ip_address TEXT,
    flagged    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX punches_eid_timestamp ON punches (eid, timestamp);
