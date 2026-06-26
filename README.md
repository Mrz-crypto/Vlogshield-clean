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
set FLASK_RUN_HOST=0.0.0.0
set FLASK_RUN_PORT=5000
```

### Production Mode (with Gunicorn)
```bash
gunicorn --bind 0.0.0.0:5000 wsgi:app
```

## Available Endpoints

- **GET** `/` - Main web interface
- **POST** `/scan` - Upload and scan an image for metadata
- **GET** `/history` - View recent scan history (last 50 scans)
- **GET** `/health` - Health check endpoint
- **GET** `/stats` - Application statistics

The `/health` endpoint includes uptime and upload-limit details. The `/stats` endpoint includes total, successful, failed, and success-rate counters.
Both endpoints also report the configured upload limit so UI and monitoring checks can confirm runtime settings.

## Usage

1. Open `http://localhost:5000` in your browser
2. Upload an image file (JPG, PNG, TIFF, HEIC, WebP)
3. The app will analyze EXIF metadata and display:
   - Privacy score (0-100)
   - Risk level (Safe, Low, Medium, High risk)
   - A short privacy summary
   - Identified sensitive metadata
   - Recommendations

## Supported Image Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- TIFF (.tiff, .tif)
- HEIC (.heic)
- WebP (.webp)

## Features

- **Privacy Scoring** - Automatic risk assessment based on metadata
- **Detailed Analysis** - Breakdown of all detected metadata
- **Image Validation** - Rejects unsupported extensions and unreadable image uploads
- **Scan History** - Track recent scans
- **Production Ready** - Health checks and request statistics
- **File Size Limit** - Max 16MB per file
- **Error Handling** - Robust error handling with logging

## Testing

Run the backend tests from the project root:

```bash
python -m unittest discover
```

The tests cover health checks, upload validation, clean-image scans, and metadata normalization.

## Configuration

Environment variables (in `.env`):
- `FLASK_ENV` - Set to 'development' or 'production'
- `FLASK_DEBUG` - Enable/disable debug mode
- `FLASK_APP` - Flask application path
- `FLASK_RUN_HOST` - Host used by `python wsgi.py`
- `FLASK_RUN_PORT` - Port used by `python wsgi.py`
- `MAX_UPLOAD_MB` - Maximum accepted upload size in megabytes

Use `.env.example` as the template for local configuration. The real `.env` file is ignored by Git.
