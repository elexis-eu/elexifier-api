"""add dict metadata

Revision ID: 3eb6ce95e65f
Revises: da2bb71b3d99
Create Date: 2019-11-27 19:13:46.711519

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3eb6ce95e65f'
down_revision = 'da2bb71b3d99'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('datasets', sa.Column('header_title', sa.String(), nullable=True),)
    op.add_column('datasets', sa.Column('header_publisher', sa.String(), nullable=True),)
    op.add_column('datasets', sa.Column('header_bibl', sa.String(), nullable=True),)


def downgrade():
    op.drop_column('datasets', 'header_title')
    op.drop_column('datasets', 'header_publisher')
    op.drop_column('datasets', 'header_bibl')
