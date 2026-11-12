# CampusMove V6 — Role-based College Transport Portal

## Windows / VS Code setup

Open this folder in VS Code. In PowerShell, run one command at a time:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and activate again. If `.env` already exists, do not overwrite it. Open http://127.0.0.1:5000.

## Local demo accounts

These demo accounts are seeded on first database initialization when `CAMPUSMOVE_DEMO_ACCOUNTS=1` (the default in `.env.example`). They are intentionally not displayed on the login page.

| Role | Email / username | Password |
|---|---|---|
| Student | student01@campusmove.demo | Student@12345 |
| Parent | parent01@campusmove.demo | Parent@12345 |
| Driver | driver01@campusmove.demo | Driver@12345 |
| Admin | admin01@campusmove.demo | Admin@12345 |
| Super Admin | superadmin01@campusmove.demo | SuperAdmin@12345 |

## Main pages

- `/student` — student ERP workspace
- `/parent` — linked children and journey notifications
- `/driver` — assigned bus, trip controls, GPS sharing and boarding desk
- `/admin` — application decisions, routes, buses and driver assignment
- `/superadmin` — account provisioning, parent-student linking and audit activity
- `/profile` — account profile
- `/tracking` — active fleet map (student, parent, admin and super admin)

## Important operational notes

- Joy University is the configured central hub. The supplied town lists are starter route coverage, not validated road itineraries. Confirm route order, stop coordinates, fares and schedules before real-world use.
- Live tracking requires a driver to start a trip and allow browser geolocation. GPS is shared from the driver's browser; outside localhost, use HTTPS.
- Parent notifications are in-app notifications generated when a driver records a boarding/alighting event. SMS, WhatsApp and push notifications are not configured.
- QR boarding currently accepts a scanned QR verification URL/token pasted into the driver form; camera scanning is not implemented.
- Speed is converted from browser geolocation metres/second to km/h before storage. ETA/route-time prediction is not implemented.
- Demo passwords are for local testing only. Change them and set a strong `SECRET_KEY` before deployment. Do not expose this demo database to the public internet.
- Back up `database.db` before replacing project files or changing schema.
