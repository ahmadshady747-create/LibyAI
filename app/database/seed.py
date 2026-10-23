"""
Seed database script for app layer:
Seeds Jasmine Shelter Hospital data into SQLite database.
"""

from seed_jasmine_hospital import seed_jasmine


def seed_database():
    seed_jasmine()
