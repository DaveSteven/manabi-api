"""Add account status and lifecycle fields; existing users become active."""
from alembic import op
import sqlalchemy as sa

revision = 'c3f1a7e29b04'
down_revision = 'b72d06e914aa'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('status', sa.String(16), nullable=False, server_default='active'))
    op.add_column('users', sa.Column('display_name', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('disabled_at', sa.DateTime(), nullable=True))
    op.execute('UPDATE users SET updated_at = created_at WHERE updated_at IS NULL')


def downgrade():
    op.drop_column('users', 'disabled_at')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'display_name')
    op.drop_column('users', 'status')
