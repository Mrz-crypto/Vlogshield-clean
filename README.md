# VlogShield - EXIF Metadata Privacy Scanner

A Flask web application that scans images for sensitive EXIF metadata and privacy risks.

## Prerequisites

- Python 3.8+
- pip

## Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. The application will automatically create necessary directories on first run.

## Running the Application

### Development Mode
```bash
python -m flask --app wsgi:app run --debug
```

The app will start at `http://localhost:5000`

You can also run the app directly:

```bash
python vlogshield/app.py
```

Optional runtime settings:

```bash
set MAX_UPLOAD_MB=16
set SCAN_RATE_LIMIT=10 per minute
set FLASK_RUN_HOST=0.0.0.0
set FLASK_RUN_PORT=5000
```

### Production Mode (with Gunicorn)
```bash
gunicorn --bind 0.0.0.0:5000 wsgi:app
```

## Available Endpoints

- **GET** `/` - Main web interface
- **GET/POST** `/register` - Create a local VlogShield account
- **GET/POST** `/login` - Sign in
- **POST** `/logout` - Sign out
- **GET** `/admin` - Admin-only user overview
- **POST** `/scan` - Upload and scan an image for metadata
- **GET** `/history` - View recent scan history (last 50 scans)
- **GET** `/health` - Health check endpoint
- **GET** `/stats` - Application statistics

The `/health` endpoint includes uptime, upload-limit, rate-limit, and storage-backend details. The `/stats` endpoint includes total, successful, failed, success-rate, stored-scan, average-score, and high-risk counters.
Both endpoints also report the configured upload limit and active storage backend so UI and monitoring checks can confirm runtime settings.
Responses include baseline browser security headers such as `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and a restrictive `Permissions-Policy`.
Scanner routes require login. `/health`, `/login`, `/register`, and static assets remain public.

## Usage

1. Open `http://localhost:5000` in your browser
2. Register an account. The first registered account becomes admin automatically.
3. Sign in, then upload an image file (JPG, PNG, TIFF, HEIC, WebP)
4. The app will analyze EXIF metadata and display:
   - Privacy score (0-100)
   - Risk level (Safe, Low, Medium, High risk)
   - A short privacy summary
   - Metadata/visual/severity risk breakdown
   - Identified sensitive metadata
   - Recommendations
   - A copyable scan report

## Supported Image Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- TIFF (.tiff, .tif)
- HEIC (.heic)
- WebP (.webp)

## Features

- **Privacy Scoring** - Automatic risk assessment for GPS, authorship, serial, and other sensitive metadata
- **User Login and Registration** - Protect scanner access behind local accounts with hashed passwords
- **Admin Dashboard** - First registered account becomes admin and can review registered users
- **Detailed Analysis** - Shows camera details, timestamps, authorship fields, and other embedded data, with lower-risk fields grouped under more details
- **Automatic Visual Redaction** - Experimental OpenCV detection is enabled by default for stronger face, possible vehicle-plate, and sensitive body-area matches
- **Editable Visual Redaction** - Review auto-detected boxes, clear false positives, draw your own boxes, choose blur strength and coverage margin, and download a redacted copy
- **Clean Copy Export** - Download a full-size PNG copy without original EXIF metadata when no visible blur is needed
- **Copyable Privacy Report** - Copy score, breakdown, risks, actions, and privacy guard notes for review
- **Image Validation** - Rejects unsupported extensions and unreadable image uploads
- **Privacy-Safe Scan History** - Track recent scans without storing original upload filenames
- **Optional MySQL Storage** - Persist privacy-safe scan history when database settings are configured
- **Scan Rate Limiting** - Throttle scan uploads with a configurable limit
- **Production Ready** - Health checks and request statistics
- **File Size Limit** - Max 16MB per file
- **Error Handling** - Robust error handling with logging

## Privacy Notes

- Uploaded images are saved only long enough to validate and scan them.
- Temporary upload files are deleted after processing.
- User passwords are hashed before storage in the local user database.
- The default local user database lives under `instance/` and is ignored by Git.
- Scan responses include privacy guard notes so the UI can show what is and is not retained.
- Automatic visual redaction returns a blurred preview when visible privacy risks are detected. Set `VISUAL_AUTO_REDACTION=0` to disable it.
- Editable redaction runs in the browser. Auto-detected boxes can be cleared or changed, and blur strength plus coverage margin can be adjusted before exporting a full-size blurred PNG copy.
- Scan history stores file type, score, grade, risk count, timestamp, and an internal scan id.
- Original uploaded filenames are not stored in scan history or normal scan-complete logs.
- Visual detection uses local computer-vision heuristics and should be reviewed before sharing. Set `VISUAL_AUTO_REDACTION=0` to disable automatic visual scanning. Set `VISUAL_BODY_HEURISTIC=0` to disable sensitive body-area detection.

## Testing

Run the backend tests from the project root:

```bash
python -m unittest discover
```

The tests cover health checks, security headers, upload validation, clean-image scans, privacy-safe history, and metadata normalization.

GitHub Actions runs the same test command on pushes and pull requests to `main`.

## MySQL Scan History

By default, scan history is stored in memory and resets when the app restarts. Configure MySQL to persist privacy-safe scan history:

Use the setup helper from PowerShell:

```powershell
.\scripts\setup_mysql.ps1
```

It prompts for the MySQL root password and the app-user password locally, creates the database/user, grants the app permissions, and updates `.env`.

Or run the SQL manually:

```sql
CREATE DATABASE vlogshield CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'vlogshield_user'@'localhost' IDENTIFIED BY 'change_me';
GRANT SELECT, INSERT, DELETE, CREATE ON vlogshield.* TO 'vlogshield_user'@'localhost';
FLUSH PRIVILEGES;
```

Then set either a single URL:

```bash
set DATABASE_URL=mysql://vlogshield_user:change_me@localhost:3306/vlogshield
```

Or individual settings:

```bash
set MYSQL_HOST=localhost
set MYSQL_PORT=3306
set MYSQL_DATABASE=vlogshield
set MYSQL_USER=vlogshield_user
set MYSQL_PASSWORD=change_me
```

The app creates the `scans` table automatically when MySQL storage is available.

## Configuration

Environment variables (in `.env`):
- `FLASK_ENV` - Set to 'development' or 'production'
- `FLASK_DEBUG` - Enable/disable debug mode
- `FLASK_APP` - Flask application path
- `FLASK_RUN_HOST` - Host used by `python wsgi.py`
- `FLASK_RUN_PORT` - Port used by `python wsgi.py`
- `MAX_UPLOAD_MB` - Maximum accepted upload size in megabytes
- `SCAN_RATE_LIMIT` - Upload throttle for `/scan`, for example `10 per minute`; set blank to disable
- `RATE_LIMIT_STORAGE_URI` - Flask-Limiter storage URI, default `memory://`
- `SECRET_KEY` - Flask session signing secret; set a strong value outside development
- `SESSION_COOKIE_SECURE` - Set to `1` when serving only over HTTPS
- `USER_DB_PATH` - Optional SQLite path for local login/register accounts
- `DATABASE_URL` - Optional MySQL connection URL for persistent scan history
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` - Optional MySQL settings when `DATABASE_URL` is not used
- `VISUAL_AUTO_REDACTION` - Set to `0` to disable experimental automatic visual blur detection
- `VISUAL_BODY_HEURISTIC` - Set to `0` to disable experimental sensitive body-area detection

Use `.env.example` as the template for local configuration. The real `.env` file is ignored by Git.
