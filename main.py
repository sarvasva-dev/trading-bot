import sys
import os
import asyncio
import logging

# Ensure the root directory is in the path for module discovery
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# v4.3.1: Zero-Loss Production Launcher
# Delegates to the core intelligence engine in nse_monitor/main.py
from nse_monitor.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"🔥 FATAL LAUNCH ERROR: {e}")
        sys.exit(1)
