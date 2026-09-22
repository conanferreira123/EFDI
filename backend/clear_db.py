import sys
# pyrefly: ignore [missing-import]
from sqlalchemy import create_engine, text, inspect
from app.core.config import settings

def truncate_all_tables():
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema='public')
    # Preserve migration version table
    tables = [t for t in tables if t != 'alembic_version']
    if not tables:
        print('No application tables found to truncate.')
        return
    stmt = 'TRUNCATE TABLE ' + ', '.join([f'"public"."{t}"' for t in tables]) + ' RESTART IDENTITY CASCADE;'
    with engine.begin() as conn:
        conn.execute(text(stmt))
    print(f'Successfully truncated {len(tables)} application tables (preserved alembic_version).')

if __name__ == '__main__':
    truncate_all_tables()
