"""Friendly launcher for the Amamio Inventory & Sales System.

    python run.py                 # this computer only (http://localhost:5000)
    set AMAMIO_HOST=0.0.0.0       # Windows: also reachable from phones/tablets
    python run.py                 #   on the same Wi-Fi (debug mode is off)

Then sign in with one of the demo accounts (see README.md / the login page).
"""
import os
import socket

from app import create_app

if __name__ == "__main__":
    app = create_app()
    host = os.environ.get("AMAMIO_HOST", "127.0.0.1")
    port = int(os.environ.get("AMAMIO_PORT", "5000"))
    # The interactive debugger must never be reachable from the network.
    debug = host in ("127.0.0.1", "localhost") and \
        os.environ.get("AMAMIO_DEBUG", "1") == "1"

    print("=" * 66)
    print(" AMAMIO FARM PRODUCTS — Inventory & Sales System")
    print(" Running on http://localhost:%d" % port)
    if host == "0.0.0.0":
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
            print(" Phones / tablets on the same Wi-Fi: http://%s:%d" % (lan_ip, port))
        except OSError:
            pass
    print("-" * 66)
    print(" Demo logins:  superadmin/super123   admin/admin123")
    print("               receiving/recv123     production/prod123")
    print("               packing/pack123       packer1/member123")
    print("               assets/assets123")
    print("=" * 66)
    app.run(host=host, port=port, debug=debug)
