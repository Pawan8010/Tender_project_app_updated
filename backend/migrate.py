import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.absolute()))

from app.database import engine, Base
from app import models

def run_migration():
    Base.metadata.create_all(bind=engine)
    print("Migration successful. New tables created.")

if __name__ == "__main__":
    run_migration()
