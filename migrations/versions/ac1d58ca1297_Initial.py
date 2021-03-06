"""empty message

Revision ID: ac1d58ca1297
Revises: 
Create Date: 2020-01-16 13:09:45.713936

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ac1d58ca1297'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('blacklist_tokens',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('token', sa.String(length=500), nullable=False),
    sa.Column('blacklisted_on', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=120), nullable=True),
    sa.Column('authenticated', sa.Boolean(), nullable=True),
    sa.Column('registered_ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('sketch_engine_uid', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('username')
    )
    op.create_table('datasets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('uid', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('size', sa.Integer(), nullable=True),
    sa.Column('file_path', sa.String(), nullable=True),
    sa.Column('xml_file_path', sa.String(), nullable=True),
    sa.Column('uploaded_ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('upload_mimetype', sa.String(), nullable=True),
    sa.Column('upload_uuid', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('lexonomy_access', sa.String(), nullable=True),
    sa.Column('lexonomy_delete', sa.String(), nullable=True),
    sa.Column('lexonomy_edit', sa.String(), nullable=True),
    sa.Column('lexonomy_status', sa.String(), nullable=True),
    sa.Column('header_title', sa.String(), nullable=True),
    sa.Column('header_publisher', sa.String(), nullable=True),
    sa.Column('header_bibl', sa.String(), nullable=True),
    sa.Column('ml_task_id', sa.String(), server_default='', nullable=True),
    sa.Column('xml_lex', sa.String(), server_default='', nullable=True),
    sa.Column('xml_ml_out', sa.String(), server_default='', nullable=True),
    sa.Column('lexonomy_ml_access', sa.String(), nullable=True),
    sa.Column('lexonomy_ml_delete', sa.String(), nullable=True),
    sa.Column('lexonomy_ml_edit', sa.String(), nullable=True),
    sa.Column('lexonomy_ml_status', sa.String(), nullable=True),
    sa.Column('pos_elements', sa.String(), nullable=True),
    sa.Column('head_elements', sa.String(), nullable=True),
    sa.Column('xpaths_for_validation', sa.String(), nullable=True),
    sa.Column('root_element', sa.String(), nullable=True),
    sa.Column('dictionary_metadata', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['uid'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('datasets_single_entry',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('dsid', sa.Integer(), nullable=True),
    sa.Column('entry_name', sa.String(), nullable=True),
    sa.Column('entry_head', sa.String(), nullable=True),
    sa.Column('entry_text', sa.String(), nullable=True),
    sa.Column('xfid', sa.String(), nullable=True),
    sa.Column('contents', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['dsid'], ['datasets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('transformers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('dsid', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('created_ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('entity_spec', sa.String(), nullable=True),
    sa.Column('transform', sa.JSON(), nullable=True),
    sa.Column('saved', sa.Boolean(), nullable=True),
    sa.Column('file_download_status', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['dsid'], ['datasets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('transformers')
    op.drop_table('datasets_single_entry')
    op.drop_table('datasets')
    op.drop_table('users')
    op.drop_table('blacklist_tokens')
    # ### end Alembic commands ###
