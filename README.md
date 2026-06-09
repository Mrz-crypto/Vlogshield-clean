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

## Usage

1. Open `http://localhost:5000` in your browser
2. Upload an image file (JPG, PNG, TIFF, HEIC, WebP)
3. The app will analyze EXIF metadata and display:
   - Privacy score (0-100)
   - Risk level (Safe, Low, Medium, High risk)
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
- **Scan History** - Track recent scans
- **Production Ready** - Health checks and request statistics
- **File Size Limit** - Max 16MB per file
- **Error Handling** - Robust error handling with logging

## Configuration

Environment variables (in `.env`):
- `FLASK_ENV` - Set to 'development' or 'production'
- `FLASK_DEBUG` - Enable/disable debug mode
- `FLASK_APP` - Flask application path

Use `.env.example` as the template for local configuration. The real `.env` file is ignored by Git.
