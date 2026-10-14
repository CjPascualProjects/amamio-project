"""Friendly launcher for the Amamio Sales & Inventory Management System.

    python run.py

Then open http://localhost:5000 and sign in with one of the demo accounts
(see README.md / the login page).
"""
from app import create_app

if __name__ == "__main__":
    app = create_app()
    print("=" * 66)
    print(" AMAMIO FARM PRODUCTS — Sales & Inventory Management System")
    print(" Running on http://localhost:5000")
    print("-" * 66)
    print(" Demo logins:  superadmin/super123   admin/admin123")
    print("               production/prod123    packing/pack123")
    print("               assets/assets123")
    print("=" * 66)
    app.run(debug=True, port=5000)
