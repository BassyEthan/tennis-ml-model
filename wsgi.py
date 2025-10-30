import os
import sys
from pathlib import Path

# Ensure project root is on sys.path before importing app
current_file = Path(__file__).resolve()
project_root_candidates = [
    current_file.parent,                # project root
    current_file.parent.parent,         # in case wsgi.py is placed under a subdir
    Path('/opt/render/project'),        # Render standard project dir
]

for path in project_root_candidates:
    try:
        abs_path = str(path.absolute())
        if path.exists() and abs_path not in sys.path:
            sys.path.insert(0, abs_path)
    except Exception:
        pass

# Optional: also add cwd
try:
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
except Exception:
    pass

# Import the Flask app
from app import app as application  # gunicorn looks for 'application'
