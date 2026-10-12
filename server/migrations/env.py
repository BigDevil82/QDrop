import os
from pathlib import Path
from alembic import context
from sqlalchemy import create_engine

url='sqlite:///'+str(Path(os.getenv('DATA_DIR','data')).resolve()/'app.db')
Path(os.getenv('DATA_DIR','data')).mkdir(parents=True,exist_ok=True)
if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction(): context.run_migrations()
