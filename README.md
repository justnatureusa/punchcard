# Punchcard

A simple time clock for employees to clock in and out by scanning their ID card.

Everything is on one page with three tabs:

- **Clock in/out**: open on a phone or tablet at the shop. Tap Clock in or Clock out, then hold the card up to the camera.
- **Employees**: add someone and print their card, or download the QR code to keep on their phone.
- **Report**: every shift with hours worked, missing clock-outs and flagged punches. Click **Edit** on a shift to fix its times or fill in a missing clock-out. Edited shifts are marked, and the original times stay in the database. Download it all as CSV for payroll.

Employees and Report ask for the admin password.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

Phones only allow the camera on `https` pages, so make a certificate once:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=punchcard" -keyout key.pem -out cert.pem
```

Then start the server:

```bash
ADMIN_PASSWORD=choose-one .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --ssl-keyfile key.pem --ssl-certfile cert.pem
```

Open `https://localhost:8000` on this computer, or `https://<this computer's IP>:8000` on the shop phone, and accept the certificate warning.

## Settings

| Variable | What it does |
|---|---|
| `ADMIN_PASSWORD` | Password for the Employees and Report tabs. Required. |
| `SHOP_NETWORK` | The shop Wi-Fi's address range, like `192.168.1.0/24`. Punches from anywhere else are flagged in the report. |
| `TIMEZONE` | Time zone for the report. Defaults to `America/Los_Angeles`. |
| `DATABASE` | Where the SQLite file lives. Defaults to `db/data.db`. |

## Rules

- You can't clock in twice or clock out twice in a row, or clock out before clocking in.
- A clock-in older than 16 hours counts as a forgotten clock-out. The person can clock in again, and the report shows that shift as missing a clock-out.
- Times are saved in UTC and shown in local time.

## Code

| File | What's in it |
|---|---|
| `static/index.html` | The whole frontend: plain HTML and JavaScript, no build step |
| `main.py` | The backend: serves the page and the `/api/...` endpoints |
| `tracker.py` | In/out rules and the shift report |
| `cards.py` | Card tokens and QR images |
| `db/` | SQLite queries and migrations |

Tests: `.venv/bin/pytest`
