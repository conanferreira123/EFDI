import sys
# pyrefly: ignore [missing-import]
from sqlalchemy import create_engine, text, inspect
from app.core.config import settings

def truncate_all_tables():
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema='public')
    if not tables:
        print('No tables found.')
        return
    stmt = 'TRUNCATE TABLE ' + ', '.join([f'"public"."{t}"' for t in tables]) + ' RESTART IDENTITY CASCADE;'
    with engine.begin() as conn:
        conn.execute(text(stmt))
    print('All tables truncated successfully.')

if __name__ == '__main__':
    truncate_all_tables()
