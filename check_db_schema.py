#!/usr/bin/env python3
"""Check database schema"""

from nse_monitor.database import Database

db = Database()
cursor = db.conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()

print("Database Schema Check:")
print("-" * 50)
for t in tables:
    print(f"  ✓ {t[0]}")

# Check if subscriptions exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
subs = cursor.fetchone()

print("\n" + "-" * 50)
if subs:
    print("✓ Subscriptions table EXISTS")
else:
    print("✗ Subscriptions table MISSING - needs migration")
    print("\nRun: python migrate_v7.py")

db.close()
