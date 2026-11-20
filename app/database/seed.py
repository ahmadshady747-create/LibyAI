"""
Seed database script for app layer:
Seeds Al-Noor Demo Clinic data into SQLite database.
"""

from seed_demo import seed_demo


def seed_database():
    seed_demo()
