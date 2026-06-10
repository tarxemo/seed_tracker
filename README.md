# Mbeya Government Seed Tracking & Allocation System

A web-based system for managing seed distribution to smallholder farmers in the Mbeya region, Tanzania.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations
python manage.py migrate

# 4. Seed demo data
python manage.py seed_data

# 5. Start server
python manage.py runserver
```

Visit: http://127.0.0.1:8000

## Demo Login Credentials

| Role              | Username          | Password  |
|-------------------|-------------------|-----------|
| Admin             | admin             | admin123  |
| Regional Officer  | regional_officer  | pass1234  |
| District Officer  | district_officer  | pass1234  |
| Ward Officer      | ward_officer      | pass1234  |
| Village Officer   | village_officer   | pass1234  |

## Features

- **Farmer Registration** – Village officers register farmers with full details
- **Seed Inventory Management** – Track seeds received by type, quantity and date
- **Seed Allocation** – Allocate seeds to verified farmers with duplicate prevention per season
- **Approval Workflow** – District/Regional officers approve/reject requests
- **SMS Notifications** – Simulated SMS on approval (integrate Africa's Talking in production)
- **Distribution Tracking** – Record actual seed collection with beneficiary confirmation
- **Reports & Analytics** – Charts by region/district/ward/village with CSV export
- **User Management** – Role-based access control for all 5 officer levels
- **Activity Logs** – Full audit trail of all system actions

## System Roles

| Role             | Responsibilities                                        |
|------------------|---------------------------------------------------------|
| Admin            | Full system access, users, settings                     |
| Regional Officer | Regional overview, reports, approve district plans      |
| District Officer | District allocations, approve ward requests             |
| Ward Officer     | Verify farmers, submit requests to district             |
| Village Officer  | Register farmers, record distributions                  |

## Production Deployment

1. Set `DEBUG = False` in settings.py
2. Set a strong `SECRET_KEY`
3. Configure a production database (PostgreSQL recommended)
4. Set `ALLOWED_HOSTS` to your domain
5. Run `python manage.py collectstatic`
6. Use gunicorn + nginx
7. For SMS: integrate Africa's Talking API in `core/utils.py`

## Tech Stack

- Django 4.2 (MVT pattern)
- Bootstrap 5.3
- Chart.js 4.4
- SQLite (dev) / PostgreSQL (production)
- Font Awesome 6.5
# ruwo_space_website
