import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
ALLOWED = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".webp"}

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
UPLOAD_DIR.mkdir(exist_ok=True)


def allowed(filename):
    return Path(filename).suffix.lower() in ALLOWED


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400
    if not allowed(file.filename):
        return jsonify({"error": "File type not supported"}), 400

    ext = Path(file.filename).suffix.lower().lstrip(".")
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}.{ext}"

    try:
        file.save(path)
        return jsonify(score_image(str(path)))
    except Exception as e:
        return jsonify({"error": f"Processing failed: {e}"}), 500
    finally:
        path.unlink(missing_ok=True)
