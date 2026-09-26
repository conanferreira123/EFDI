"""add_structured_business_tables_and_chunk_section

Revision ID: 361bf56d16a1
Revises: 014cab3b4e0b
Create Date: 2026-09-22 13:44:47.533341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '361bf56d16a1'
down_revision: Union[str, Sequence[str], None] = '014cab3b4e0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to include structured business layer, document_chunks section, and indexes."""

    # 1. Create vendors table
    op.create_table(
        'vendors',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('canonical_name', sa.String(length=255), nullable=False),
        sa.Column('vendor_code', sa.String(length=50), nullable=True),
        sa.Column('tax_id', sa.String(length=50), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_vendors')),
    )
    op.create_index('ix_vendors_canonical_name', 'vendors', ['canonical_name'], unique=False)
    op.create_index('ix_vendors_vendor_code', 'vendors', ['vendor_code'], unique=True)
    op.create_index('ix_vendors_tax_id', 'vendors', ['tax_id'], unique=False)

    # 2. Create vendor_aliases table
    op.create_table(
        'vendor_aliases',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('vendor_id', sa.Integer(), nullable=False),
        sa.Column('alias', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=op.f('fk_vendor_aliases_vendor_id_vendors'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_vendor_aliases')),
        sa.UniqueConstraint('vendor_id', 'alias', name='uq_vendor_aliases_vendor_alias'),
    )
    op.create_index('ix_vendor_aliases_vendor_id', 'vendor_aliases', ['vendor_id'], unique=False)
    op.create_index('ix_vendor_aliases_alias', 'vendor_aliases', ['alias'], unique=False)

    # 3. Create invoices table
    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('source_extraction_result_id', sa.Integer(), nullable=True),
        sa.Column('invoice_number', sa.String(length=100), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('vendor_id', sa.Integer(), nullable=True),
        sa.Column('buyer_name', sa.String(length=255), nullable=True),
        sa.Column('buyer_tax_id', sa.String(length=50), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('subtotal_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('tax_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('discount_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('shipping_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('rounding_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('other_charges_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('grand_total_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('po_number', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_invoices_document_id_documents'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_extraction_result_id'], ['extraction_results.id'], name=op.f('fk_invoices_source_extraction_result_id_extraction_results'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=op.f('fk_invoices_vendor_id_vendors'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoices')),
        sa.UniqueConstraint('document_id', name='uq_invoices_document_id'),
    )
    op.create_index('ix_invoices_document_id', 'invoices', ['document_id'], unique=True)
    op.create_index('ix_invoices_source_extraction_result_id', 'invoices', ['source_extraction_result_id'], unique=False)
    op.create_index('ix_invoices_invoice_number', 'invoices', ['invoice_number'], unique=False)
    op.create_index('ix_invoices_invoice_date', 'invoices', ['invoice_date'], unique=False)
    op.create_index('ix_invoices_vendor_id', 'invoices', ['vendor_id'], unique=False)
    op.create_index('ix_invoices_grand_total_amount', 'invoices', ['grand_total_amount'], unique=False)
    op.create_index('ix_invoices_po_number', 'invoices', ['po_number'], unique=False)

    # 4. Create invoice_line_items table
    op.create_table(
        'invoice_line_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('uom', sa.String(length=30), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('net_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('tax_rate', sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column('tax_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('gross_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_invoice_line_items_invoice_id_invoices'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_line_items')),
    )
    op.create_index('ix_invoice_line_items_invoice_id', 'invoice_line_items', ['invoice_id'], unique=False)
    op.create_index('ix_invoice_line_items_description', 'invoice_line_items', ['description'], unique=False)

    # 5. Create payment_obligations table
    op.create_table(
        'payment_obligations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('amount_due', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('amount_paid', sa.Numeric(precision=15, scale=2), server_default=sa.text("'0.00'"), nullable=False),
        sa.Column('amount_outstanding', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=30), server_default=sa.text("'UNKNOWN'"), nullable=False),
        sa.Column('payment_terms', sa.Text(), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('early_payment_deadline', sa.Date(), nullable=True),
        sa.Column('early_payment_discount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('late_payment_penalty', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_payment_obligations_invoice_id_invoices'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_obligations')),
        sa.UniqueConstraint('invoice_id', name='uq_payment_obligations_invoice_id'),
    )
    op.create_index('ix_payment_obligations_invoice_id', 'payment_obligations', ['invoice_id'], unique=True)
    op.create_index('ix_payment_obligations_due_date', 'payment_obligations', ['due_date'], unique=False)
    op.create_index('ix_payment_obligations_status', 'payment_obligations', ['status'], unique=False)

    # 6. Create invoice_payments table
    op.create_table(
        'invoice_payments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('payment_reference', sa.String(length=100), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_invoice_payments_invoice_id_invoices'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_payments')),
    )
    op.create_index('ix_invoice_payments_invoice_id', 'invoice_payments', ['invoice_id'], unique=False)
    op.create_index('ix_invoice_payments_payment_date', 'invoice_payments', ['payment_date'], unique=False)

    # 7. Modify document_chunks: add section column and index
    op.add_column('document_chunks', sa.Column('section', sa.String(length=50), nullable=True))
    op.create_index('ix_document_chunks_section', 'document_chunks', ['section'], unique=False)

    # 8. Create missing B-tree indexes on documents table
    op.create_index('ix_documents_uploaded_by', 'documents', ['uploaded_by'], unique=False)
    op.create_index('ix_documents_created_at', 'documents', ['created_at'], unique=False)
    op.create_index('ix_documents_is_deleted', 'documents', ['is_deleted'], unique=False)
    op.create_index('ix_documents_document_type', 'documents', ['document_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop document indexes
    op.drop_index('ix_documents_document_type', table_name='documents')
    op.drop_index('ix_documents_is_deleted', table_name='documents')
    op.drop_index('ix_documents_created_at', table_name='documents')
    op.drop_index('ix_documents_uploaded_by', table_name='documents')

    # Drop document_chunks column & index
    op.drop_index('ix_document_chunks_section', table_name='document_chunks')
    op.drop_column('document_chunks', 'section')

    # Drop business tables in reverse foreign-key dependency order
    op.drop_table('invoice_payments')
    op.drop_table('payment_obligations')
    op.drop_table('invoice_line_items')
    op.drop_table('invoices')
    op.drop_table('vendor_aliases')
    op.drop_table('vendors')
