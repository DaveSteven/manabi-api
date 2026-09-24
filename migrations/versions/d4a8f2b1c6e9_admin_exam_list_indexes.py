"""Add indexes supporting admin exam list filtering, sorting and counts."""
from alembic import op

revision = 'd4a8f2b1c6e9'
down_revision = 'c3f1a7e29b04'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_exams_level_year_month', 'exams', ['level', 'year', 'month'], unique=False)
    op.create_index('ix_occurrences_exam_status', 'occurrences', ['exam_id', 'status'], unique=False)
    op.create_index('ix_quality_issues_occurrence_import', 'quality_issues', ['occurrence_id', 'import_id'], unique=False)


def downgrade():
    op.drop_index('ix_quality_issues_occurrence_import', table_name='quality_issues')
    op.drop_index('ix_occurrences_exam_status', table_name='occurrences')
    op.drop_index('ix_exams_level_year_month', table_name='exams')
