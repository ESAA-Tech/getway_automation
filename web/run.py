#!/usr/bin/env python3
"""
Launcher script for Edge Gateway Web Command Center.
"""

import os
import sys

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.server import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8085))
    print(f"\n" + "=" * 75)
    print(f"  CITY-WIDE EDGE GATEWAY COMMAND CENTER")
    print(f"  Open in Browser: http://127.0.0.1:{port}")
    print("=" * 75 + "\n")
    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    except OSError as e:
        print(f"\n[!] Port {port} is occupied or blocked: {e}")
        fallback_port = 8086
        print(f"[*] Retrying on fallback port http://127.0.0.1:{fallback_port} ...\n")
        app.run(host="0.0.0.0", port=fallback_port, debug=False)
