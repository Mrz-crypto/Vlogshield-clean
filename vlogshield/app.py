from datetime import datetime, timezone
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import GPSTAGS, TAGS

try:
    from .storage import create_scan_store
except ImportError:
    from storage import create_scan_store

# Configure logging for production monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    logger.warning("pillow-heif is unavailable; HEIC uploads cannot be decoded.")

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
ALLOWED = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".webp"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "16")) * 1024 * 1024
SCAN_RATE_LIMIT = os.getenv("SCAN_RATE_LIMIT", "10 per minute")
RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")
STARTED_AT = datetime.now(timezone.utc)

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["JSON_SORT_KEYS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-this-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
UPLOAD_DIR.mkdir(exist_ok=True)
SKIP = {"MakerNote", "PrintImageMatching"}
SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Request counter for analytics
request_count = {"total": 0, "successful": 0, "failed": 0}
scan_store = create_scan_store()


def configure_limiter():
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
    except ImportError:
        logger.warning("Flask-Limiter is unavailable; scan rate limiting is disabled.")
        return None

    return Limiter(
        get_remote_address,
        app=app,
        default_limits=[],
        storage_uri=RATE_LIMIT_STORAGE_URI,
    )


limiter = configure_limiter()


def scan_rate_limit(route):
    if limiter is None or not SCAN_RATE_LIMIT:
        return route
    return limiter.limit(SCAN_RATE_LIMIT)(route)


def normalize_metadata_value(value):
    """Convert EXIF values into JSON-safe primitives."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {
            _normalize_metadata_key(key): normalize_metadata_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [normalize_metadata_value(item) for item in value]
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            return float(value)
        except (TypeError, ZeroDivisionError):
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_metadata_key(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _json_error(message, status_code):
    request_count["failed"] += 1
    return jsonify({"error": message}), status_code


def _uptime_seconds():
    return round((datetime.now(timezone.utc) - STARTED_AT).total_seconds(), 2)


def validate_image(path):
    try:
        with Image.open(path) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Uploaded file is not a readable image.") from exc


def extract_exif(path):
    try:
        with Image.open(path) as image:
            raw = image.getexif() or {}
    except Exception as e:
        logger.warning(f"EXIF extraction failed for {path}: {e}")
        return {}

    out = {}
    # GPS is a nested EXIF IFD (tag 34853), rather than an ordinary top-level
    # field. Some HEIC decoders expose only this nested form, so reading the
    # value directly can make a location-tagged original appear to have no GPS.
    gps_tag = next((tag for tag, name in TAGS.items() if name == "GPSInfo"), 34853)
    try:
        gps_values = raw.get_ifd(gps_tag)
    except (AttributeError, KeyError, TypeError, ValueError):
        gps_values = raw.get(gps_tag, {})

    if gps_values:
        gps = {
            GPSTAGS.get(key, str(key)): normalize_metadata_value(value)
            for key, value in gps_values.items()
        }
        coordinates = _format_gps_coordinates(gps)
        if coordinates:
            gps["Coordinates"] = coordinates
        out["GPS"] = gps

    for tag_id, value in dict(raw).items():
        name = TAGS.get(tag_id, str(tag_id))
        if name == "GPSInfo":
            # Handled above with get_ifd(), which also works when this top-level
            # value is merely an offset into the nested GPS metadata.
            continue
        else:
            out[name] = normalize_metadata_value(value)
    return out


def _format_gps_coordinates(gps):
    """Return GPS EXIF degrees/minutes/seconds as readable decimal coordinates."""
    latitude = _gps_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
    longitude = _gps_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
    if latitude is None or longitude is None:
        return None
    return f"{latitude:.6f}, {longitude:.6f}"


def _gps_decimal(value, direction):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        degrees, minutes, seconds = (float(part) for part in value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    decimal = degrees + minutes / 60 + seconds / 3600
    if str(direction).upper() in {"S", "W"}:
        decimal *= -1
    return decimal


@app.before_request
def count_request():
    if request.endpoint != "static":
        request_count["total"] += 1


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
    return response


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": _uptime_seconds(),
        "max_upload_mb": round(MAX_UPLOAD_BYTES / (1024 * 1024)),
        "scan_rate_limit": SCAN_RATE_LIMIT or "disabled",
        "storage_backend": scan_store.name,
    }), 200

@app.route("/stats", methods=["GET"])
def get_stats():
    """Return application statistics."""
    logger.info(f"Stats requested - Total: {request_count['total']}, Success: {request_count['successful']}, Failed: {request_count['failed']}")
    return jsonify({
        **request_count,
        **scan_store.summary(),
        "uptime_seconds": _uptime_seconds(),
        "max_upload_mb": round(MAX_UPLOAD_BYTES / (1024 * 1024)),
        "storage_backend": scan_store.name,
        "success_rate": round(request_count["successful"] / max(request_count["total"], 1), 3),
    }), 200


@app.errorhandler(413)
def too_large(_error):
    return _json_error("File too large", 413)


@app.errorhandler(404)
def not_found(_error):
    return _json_error("Endpoint not found", 404)


def register_routes():
    try:
        from . import auth
        from . import scorer
    except ImportError:
        import auth
        import scorer


register_routes()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
