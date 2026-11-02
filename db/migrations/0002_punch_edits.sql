-- When a manager changes a punch's time, keep the time it was first recorded at.
ALTER TABLE punches ADD COLUMN original_timestamp TEXT;
ALTER TABLE punches ADD COLUMN edited_at TEXT;
