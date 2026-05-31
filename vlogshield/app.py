import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from scorer import score_image

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

