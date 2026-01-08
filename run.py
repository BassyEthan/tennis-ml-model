#!/usr/bin/env python3
"""
Supervisor entrypoint for the Tennis Trading System.

This script starts:
1. Market Data Service (port 5002) - Background poller + Flask app
2. UI + Trading App (port 5001) - Flask app

Architectural guarantees:
- Market Data Service is the ONLY place that calls Kalshi API
- Background poller starts exactly once
- Both Flask apps run in separate threads
- No Flask reloader (prevents duplicate threads)
"""

import sys
import os
import time
import signal
import threading
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Set working directory to project root
os.chdir(project_root)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import app factories and service
from src.services.market_data_service import start_market_data_service, stop_background_poller
from src.services.market_data_app import create_market_data_app
from app.app import create_ui_app

# Global references for cleanup
_market_data_app = None
_ui_app = None
_market_data_thread = None
_ui_thread = None
_shutdown_event = threading.Event()


def run_flask_app(app, port, name):
    """
    Run a Flask app in a thread.
    
    Args:
        app: Flask application instance
        port: Port to run on
        name: Name for logging
    """
    try:
        logger.info(f"Starting {name} on port {port}")
        print(f"   🚀 {name} starting on http://localhost:{port}")
        
        # Use Werkzeug's development server directly for better thread compatibility
        from werkzeug.serving import make_server
        
        server = make_server('0.0.0.0', port, app, threaded=True)
        logger.info(f"{name} server created, starting...")
        print(f"   ✅ {name} server started on http://localhost:{port}")
        server.serve_forever()
        
    except OSError as e:
        if "Address already in use" in str(e) or e.errno == 48:
            logger.error(f"Port {port} is already in use for {name}")
            print(f"   ❌ Port {port} is already in use - is another instance running?")
        else:
            logger.error(f"OSError in {name}: {e}", exc_info=True)
            print(f"   ❌ {name} failed to start: {e}")
    except Exception as e:
        logger.error(f"Error in {name}: {e}", exc_info=True)
        print(f"   ❌ {name} failed to start: {e}")
        import traceback
        traceback.print_exc()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Received shutdown signal, stopping services...")
    _shutdown_event.set()
    
    # Stop background poller
    try:
        stop_background_poller()
    except Exception as e:
        logger.error(f"Error stopping poller: {e}")
    
    # Stop trading loop
    try:
        from app.app import auto_trader
        if auto_trader is not None:
            auto_trader.stop_trading_loop()
    except Exception as e:
        logger.error(f"Error stopping trading loop: {e}")
    
    # Flask apps will stop when threads exit
    logger.info("Shutdown complete")
    sys.exit(0)


def main():
    """Main supervisor function."""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        print("=" * 70)
        print("🚀 Starting Tennis Trading System Supervisor")
        print("=" * 70)
        print()
        
        # Step 1: Start Market Data Service (blocking initial fetch + poller)
        print("📡 Step 1: Starting Market Data Service...")
        print("   This will perform an initial fetch from Kalshi (may take 10-30 seconds)")
        start_market_data_service()
        print("   ✅ Market Data Service ready (poller running)")
        print()
        
        # Step 2: Create Flask app instances
        print("🔧 Step 2: Creating Flask applications...")
        try:
            market_data_app = create_market_data_app()
            print("   ✅ Market Data Service app created")
        except Exception as e:
            logger.error(f"Failed to create Market Data Service app: {e}", exc_info=True)
            print(f"   ❌ Failed to create Market Data Service app: {e}")
            raise
        
        try:
            ui_app = create_ui_app()
            print("   ✅ UI + Trading app created")
        except Exception as e:
            logger.error(f"Failed to create UI app: {e}", exc_info=True)
            print(f"   ❌ Failed to create UI app: {e}")
            raise
        print()
        
        # Step 3: Start Flask apps in background threads
        print("🌐 Step 3: Starting Flask servers...")
        
        # Market Data Service on port 5002
        # NOTE: Non-daemon threads so they don't exit when main thread exits
        market_data_thread = threading.Thread(
            target=run_flask_app,
            args=(market_data_app, 5002, "Market Data Service"),
            daemon=False,  # Non-daemon so it keeps running
            name="MarketDataService"
        )
        market_data_thread.start()
        
        # Wait for Market Data Service to start
        print("   ⏳ Waiting for Market Data Service to start...")
        time.sleep(3)
        
        # UI + Trading App on port 5001
        ui_thread = threading.Thread(
            target=run_flask_app,
            args=(ui_app, 5001, "UI + Trading App"),
            daemon=False,  # Non-daemon so it keeps running
            name="UITradingApp"
        )
        ui_thread.start()
        
        # Wait for UI to start
        print("   ⏳ Waiting for UI + Trading App to start...")
        time.sleep(3)
        
        # Store references for cleanup
        global _market_data_app, _ui_app, _market_data_thread, _ui_thread
        _market_data_app = market_data_app
        _ui_app = ui_app
        _market_data_thread = market_data_thread
        _ui_thread = ui_thread
        
        # Step 4: Start automatic trading loop (if auto_trader is available)
        print("🤖 Step 4: Starting automatic trading loop...")
        try:
            # Import auto_trader from UI app (it's initialized there)
            from app.app import auto_trader
            
            if auto_trader is not None:
                # Start background trading loop (runs every 1 minute for testing)
                # Can be configured via environment variable: TRADING_LOOP_INTERVAL_MINUTES
                loop_interval_minutes = int(os.getenv("TRADING_LOOP_INTERVAL_MINUTES", "1"))  # Changed to 1 minute for testing
                auto_trader.start_trading_loop(loop_interval_minutes=loop_interval_minutes)
                print(f"   ✅ Automatic trading loop started (interval: {loop_interval_minutes} minute{'s' if loop_interval_minutes != 1 else ''})")
                print(f"   Dry run mode: {auto_trader.dry_run}")
            else:
                print("   ⚠️  Auto trader not available - trading loop skipped")
        except Exception as e:
            logger.warning(f"Failed to start trading loop: {e}", exc_info=True)
            print(f"   ⚠️  Failed to start trading loop: {e}")
            # Don't fail the entire startup if trading loop fails
        print()
        
        # Verify threads are still alive
        if not market_data_thread.is_alive():
            logger.error("Market Data Service thread died immediately after start!")
            print("   ❌ Market Data Service thread died - check logs above")
        else:
            print("   ✅ Market Data Service: http://localhost:5002")
        
        if not ui_thread.is_alive():
            logger.error("UI thread died immediately after start!")
            print("   ❌ UI + Trading App thread died - check logs above")
        else:
            print("   ✅ UI + Trading App: http://localhost:5001")
        
        print()
        print("=" * 70)
        if market_data_thread.is_alive() and ui_thread.is_alive():
            print("✅ System is running!")
        else:
            print("⚠️  Some services failed to start - check logs above")
        print("=" * 70)
        print()
        print("Press Ctrl+C to stop all services")
        print()
        
        # Keep main thread alive
        try:
            while not _shutdown_event.is_set():
                time.sleep(1)
                
                # Check if threads are still alive
                if not market_data_thread.is_alive():
                    logger.error("Market Data Service thread died!")
                    break
                if not ui_thread.is_alive():
                    logger.error("UI thread died!")
                    break
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
            signal_handler(signal.SIGINT, None)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
