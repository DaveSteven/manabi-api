"""Add media content versions; backfill existing files with scripts.hash_assets."""
from alembic import op
import sqlalchemy as sa

revision = 'b72d06e914aa'
down_revision = 'a81c92b3d104'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('assets', sa.Column('content_hash', sa.String(64), nullable=True))


def downgrade():
    op.drop_column('assets', 'content_hash')
