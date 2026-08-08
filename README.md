# CAGH Backend API — HerWell Application

![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Django](https://img.shields.io/badge/django-5.0-green.svg)
![DRF](https://img.shields.io/badge/django--rest--framework-3.14-red.svg)
![Docker](https://img.shields.io/badge/docker-enabled-blue.svg)

Backend RESTful API and WebSocket service for **CAGH Adolescent Girls Healthcare (HerWell Mobile Application)**. Built using Django REST Framework, PostgreSQL, Redis, Celery, and Docker.

---

## Architecture & Core Modules

The platform is organized into modular domain services:

* **Users & Authentication (`apps/users`)** — Multi-factor registration (Email/Phone), OTP verification, JWT sessions, role management (Patients, Midwives, Admins), and user profiles/preferences.
* **Common & Localization (`apps/common`)** — Multi-language support (English & Amharic), healthcare facilities directory, activity audit logs, and reports.
* **Midwives (`apps/midwives`)** — Professional credentials, verification workflows, and availability management.
* **Appointments (`apps/appointments`)** — Appointment booking, scheduling, and status tracking.
* **Consultations (`apps/consultations`)** — Telehealth consultation sessions, notes, and medical records.
* **Real-time Chat (`apps/chat`)** — Real-time messaging between users and healthcare providers via WebSockets.
* **AI Assistant (`apps/ai_assistant`)** — AI-driven adolescent health guidance and Q&A.
* **Learning Center (`apps/learning`)** — Health articles, educational resources, and content categorization.
* **Notifications (`apps/notifications`)** — Push notifications and SMS alerts.
* **Reviews & Feedback (`apps/reviews`)** — Provider ratings and user feedback.

---

## Technology Stack

| Component | Technology |
| :--- | :--- |
| **Language** | Python 3.12 |
| **Web Framework** | Django 5.0 + Django REST Framework |
| **Authentication** | SimpleJWT (JSON Web Tokens) + OTP Verification |
| **Database** | PostgreSQL 16 |
| **Cache & Message Broker** | Redis 7 |
| **Asynchronous Tasks** | Celery |
| **Documentation** | drf-spectacular (OpenAPI 3.0 / Swagger UI) |
| **Containerization** | Docker & Docker Compose |

---

## Getting Started

### 1. Prerequisites
* [Docker](https://www.docker.com/) and Docker Compose installed on your system.

### 2. Environment Setup
Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```

### 3. Build & Run Containerized Services
```bash
docker compose up -d --build
```

### 4. Apply Database Migrations
```bash
docker compose exec web python manage.py migrate
```

### 5. (Optional) Create Superuser (Admin Dashboard Access)
```bash
docker compose exec web python manage.py createsuperuser
```


---

## API Documentation

When the application is running locally, access the interactive API documentation at:

* **Swagger UI:** `http://localhost:8000/api/docs/`
* **ReDoc:** `http://localhost:8000/api/redoc/`
* **OpenAPI Schema:** `http://localhost:8000/api/schema/`

---

## Testing

Run the automated test suite inside the container:

```bash
docker compose exec web python manage.py test
```
