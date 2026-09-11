"""Add explicit administrator role; existing accounts remain ordinary users."""
from alembic import op
import sqlalchemy as sa

revision = 'a81c92b3d104'
down_revision = 'fddc8c6de4ce'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('users', 'is_admin')
