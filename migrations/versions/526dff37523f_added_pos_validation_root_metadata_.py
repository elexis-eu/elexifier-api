"""added pos, validation, root metadata columns

Revision ID: 526dff37523f
Revises: 36ed5ba918fe
Create Date: 2019-12-26 09:22:51.044068

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '526dff37523f'
down_revision = '36ed5ba918fe'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('datasets', sa.Column('pos_elements', sa.String(), nullable=True))
    op.add_column('datasets', sa.Column('xpaths_for_validation', sa.String(), nullable=True))
    op.add_column('datasets', sa.Column('root_element', sa.String(), nullable=True))
    op.add_column('datasets', sa.Column('metadata', sa.String(), nullable=True))


def downgrade():
    op.drop_column('datasets', 'pos_elements')
    op.drop_column('datasets', 'xpaths_for_validation')
    op.drop_column('datasets', 'root_element')
    op.drop_column('datasets', 'metadata')
