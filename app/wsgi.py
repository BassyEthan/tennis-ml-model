"""
WSGI entry point for production deployment (Gunicorn, etc.)
"""
import os
import sys
from pathlib import Path

# Add project root to Python path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Import Flask app
from app.app import app as application

if __name__ == "__main__":
    application.run()
