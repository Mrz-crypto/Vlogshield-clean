"""WSGI entry point for production deployment."""
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from vlogshield.app import app

if __name__ == "__main__":
    app.run()
