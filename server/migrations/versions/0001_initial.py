from alembic import op
from app.store import DDL
revision='0001'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    for sql in DDL.split(';'):
        if sql.strip():op.execute(sql)
def downgrade():
    for table in ('receipts','transfers','enrollments','devices'):op.execute('DROP TABLE '+table)
