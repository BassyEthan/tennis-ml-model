#!/usr/bin/env python3
"""
Simple entry point to run the Flask application.
Usage: python run.py
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Set working directory to project root
os.chdir(project_root)

# Import and run the app
if __name__ == '__main__':
    try:
        from app.app import app
        port = int(os.environ.get('PORT', 5001))
        print(f"\n🚀 Starting Tennis Trading System")
        print(f"   URL: http://0.0.0.0:{port}")
        print(f"   Local: http://localhost:{port}\n")
        app.run(debug=True, host='0.0.0.0', port=port)
    except Exception as e:
        print(f"❌ Error starting application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

