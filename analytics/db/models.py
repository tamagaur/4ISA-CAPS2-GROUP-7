"""
analytics.db.models — SQLAlchemy ORM table definitions.

Mirrors analytics/db/schema.sql EXACTLY — table names, column names, types,
nullability, CHECK constraints, UNIQUE constraints, and indexes. If you ever
need to change a column, change it in schema.sql first, then update this
file to match. They must never diverge (this file's own original TODO said
so, and it's the only way DEC-01's audit trail stays trustworthy: the DDL
is the source of truth, this is just Python's view of it).

Section numbering below matches schema.sql's section comments 1:1 so the
two files are easy to diff against each other.

Table names are lowercase (e.g. "date_dimension") because schema.sql uses
unquoted identifiers, which Postgres folds to lowercase automatically —
this is not a typo, see tests/etl/test_load.py which already assumes
lowercase table names like "sales_fact".

NOTE ON GRAIN (DEC-02 / DEC-03) — do not "clean this up" later:
  - SalesFact / PurchaseFact / SalesReturnFact have NO product_id — their
    source files are invoice-grain with no SKU column. Adding one without
    a real source column behind it would be fabrication.
  - InventoryFact / SellOutFact / UnileverSkuDemandFact DO carry
    product_id — their source files carry real product/category identity.
"""
from __future__ import annotations

import datetime
import decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for every mapped table in this module."""
    pass


# ============================================================
# SECTION 1 — DIMENSION TABLES (DEC-06: SCD Type 1, no history columns)
# ============================================================

class DateDimension(Base):
    __tablename__ = "date_dimension"

    date_key: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)   # 1=Mon .. 7=Sun (ISO)
    day_name: Mapped[str] = mapped_column(Text, nullable=False)
    week_of_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month_name: Mapped[str] = mapped_column(Text, nullable=False)
    quarter: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fiscal_period: Mapped[str | None] = mapped_column(Text)   # NULL until SSM fiscal calendar is confirmed


class ProductDimension(Base):
    """Covers Unilever SKUs AND Del Monte category/brand nodes (DEC-03) —
    one dimension, two legitimate kinds of 'product identity', not a
    workaround. `grain` tells you which columns are populated."""
    __tablename__ = "product_dimension"
    __table_args__ = (
        CheckConstraint("principal IN ('unilever', 'delmonte')", name="ck_product_dimension_principal"),
        CheckConstraint("grain IN ('sku', 'category')", name="ck_product_dimension_grain"),
        UniqueConstraint("principal", "grain", "sku_code", "category_path", name="uq_product_dimension_identity"),
    )

    product_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    grain: Mapped[str] = mapped_column(Text, nullable=False)
    sku_code: Mapped[str | None] = mapped_column(Text)             # Unilever real SKU; NULL for Del Monte rows
    category_path: Mapped[str | None] = mapped_column(Text)        # e.g. '/ACE/BASE'; NULL for Unilever rows
    product_name: Mapped[str | None] = mapped_column(Text)
    pack_size: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)


class CustomerDimension(Base):
    __tablename__ = "customer_dimension"
    __table_args__ = (
        CheckConstraint("principal IN ('unilever', 'delmonte')", name="ck_customer_dimension_principal"),
        UniqueConstraint("customer_name", "region", "principal", name="uq_customer_dimension_identity"),
    )

    customer_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)               # pangasinan / ilocos / la_union
    principal: Mapped[str | None] = mapped_column(Text)


class SalesmanDimension(Base):
    __tablename__ = "salesman_dimension"

    salesman_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    salesman_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class SupplierDimension(Base):
    __tablename__ = "supplier_dimension"
    __table_args__ = (
        CheckConstraint("principal IN ('unilever', 'delmonte')", name="ck_supplier_dimension_principal"),
    )

    supplier_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    principal: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


# ============================================================
# SECTION 2 — TRANSACTION MART (invoice grain, DEC-02)
# No product_key: source files have no SKU column at this grain.
# UNIQUE constraints encode DEC-04's source-of-truth map so a demoted
# cross-check sheet can never be double-loaded alongside the real one.
# ============================================================

class SalesFact(Base):
    """Fixed 2026-08: restricted to Del Monte only. Unilever's real Sales
    system-of-record (SSIS RAW_DATA) has no invoice/reference column at
    all - see schema.sql's comment on this table for the full rationale
    and the ssis_summary orphaning consequence. Mirror that comment if
    you change this again."""
    __tablename__ = "sales_fact"
    __table_args__ = (
        CheckConstraint("principal = 'delmonte'", name="ck_sales_fact_principal"),
        UniqueConstraint("invoice_num", "principal", "region", name="uq_sales_fact_natural_key"),
        Index("ix_sales_fact_principal_period", "principal", "_period"),
        Index("ix_sales_fact_customer", "customer_key"),
    )

    sales_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    invoice_num: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_date: Mapped[datetime.date | None] = mapped_column(ForeignKey("date_dimension.date_key"))
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    branch_code: Mapped[str | None] = mapped_column(Text)          # TEXT: leading zeros are real data
    customer_key: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customer_dimension.customer_key"))
    salesman_key: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("salesman_dimension.salesman_key"))
    untaxed_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    discount_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    discount_rate_label: Mapped[str | None] = mapped_column(Text)  # text label, never numeric
    tax_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    net_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    balance: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    _outlier_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    _src_file: Mapped[str] = mapped_column(Text, nullable=False)
    _src_sheet: Mapped[str] = mapped_column(Text, nullable=False)
    _period: Mapped[str] = mapped_column(Text, nullable=False)     # 'YYYY-MM'

    customer: Mapped["CustomerDimension | None"] = relationship()
    salesman: Mapped["SalesmanDimension | None"] = relationship()


class PurchaseFact(Base):
    __tablename__ = "purchase_fact"
    __table_args__ = (
        CheckConstraint("principal IN ('unilever', 'delmonte')", name="ck_purchase_fact_principal"),
        UniqueConstraint("invoice_num", "principal", "region", name="uq_purchase_fact_natural_key"),
        Index("ix_purchase_fact_principal_period", "principal", "_period"),
    )

    purchase_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    invoice_num: Mapped[str] = mapped_column(Text, nullable=False)   # 'BILL/...' or PO ref
    invoice_date: Mapped[datetime.date | None] = mapped_column(ForeignKey("date_dimension.date_key"))
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    supplier_key: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("supplier_dimension.supplier_key"))
    net_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    units_received: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))  # feeds clean.compute_bo_rate
    _src_file: Mapped[str] = mapped_column(Text, nullable=False)
    _src_sheet: Mapped[str] = mapped_column(Text, nullable=False)
    _period: Mapped[str] = mapped_column(Text, nullable=False)

    supplier: Mapped["SupplierDimension | None"] = relationship()


class SalesReturnFact(Base):
    """return_type is GS/BO when known — the RMR 'ONE PAGER' sheet (= GS
    union BO) is a demoted cross-check per DEC-04 and must never be
    loaded here. NULL means the source didn't distinguish GS/BO at all
    (the pre-2025 Sales Return shapes), not unknown/bad data.

    Fixed 2026-08: invoice_num dropped from the natural key — confirmed
    against real rmr_gs_bo data that it never exists as a producible
    column at all (0/538 real rows). See schema.sql's comment on this
    table for the full rationale.

    Fixed 2026-08 (Sales Return driver build): return_type made nullable
    — was NOT NULL, which made the ~10-12 of 19 real Sales Return files
    predating the 2025 GS/BO-split report format permanently unloadable.
    See schema.sql's comment on this column for the full rationale, and
    its comment on the UNIQUE constraint below for the open NULL-vs-NULL
    dedup gap this reintroduces (flagged, not fixed, this pass)."""
    __tablename__ = "salesreturn_fact"
    __table_args__ = (
        CheckConstraint(
            "return_type IS NULL OR return_type IN ('GS', 'BO')",
            name="ck_salesreturn_fact_return_type",
        ),
        CheckConstraint("principal IN ('unilever', 'delmonte')", name="ck_salesreturn_fact_principal"),
        UniqueConstraint(
            "return_slip_num", "principal", "region", "return_type",
            name="uq_salesreturn_fact_natural_key",
        ),
        Index("ix_salesreturn_fact_principal_period", "principal", "_period"),
    )

    return_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    return_slip_num: Mapped[str | None] = mapped_column(Text)       # primary natural-key half
    invoice_num: Mapped[str | None] = mapped_column(Text)           # kept for schema-generality; not in the key, see class docstring
    return_type: Mapped[str | None] = mapped_column(Text)
    return_date: Mapped[datetime.date | None] = mapped_column(ForeignKey("date_dimension.date_key"))
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    net_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    bo_units: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))  # only when return_type='BO'
    _src_file: Mapped[str] = mapped_column(Text, nullable=False)
    _src_sheet: Mapped[str] = mapped_column(Text, nullable=False)
    _period: Mapped[str] = mapped_column(Text, nullable=False)


# ============================================================
# SECTION 3 — PRODUCT MART (SKU / category grain, DEC-02 + DEC-03)
# ============================================================

class InventoryFact(Base):
    __tablename__ = "inventory_fact"
    __table_args__ = (
        CheckConstraint("principal IN ('unilever', 'delmonte')", name="ck_inventory_fact_principal"),
        UniqueConstraint("sku_code", "snapshot_date", "region", name="uq_inventory_fact_natural_key"),
        Index("ix_inventory_fact_product", "product_key"),
    )

    inventory_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_key: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_dimension.product_key"))
    sku_code: Mapped[str] = mapped_column(Text, nullable=False)     # kept raw alongside the FK
    # DEC-12: synthetic first-of-_period marker (these exports are
    # monthly, no real day-of-month exists) — see schema.sql for the full
    # note. _period below is the real join key.
    snapshot_date: Mapped[datetime.date] = mapped_column(ForeignKey("date_dimension.date_key"), nullable=False)
    _period: Mapped[str | None] = mapped_column(Text)               # 'YYYY-MM', the real period key
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    quantity_on_hand: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    # DEC-11: comparable-unit quantity, Del Monte only for now — set
    # directly from PCS (pieces); CAS/PKG deliberately NOT converted (no
    # confirmed Del Monte pack_size). See schema.sql for the full note.
    quantity_pieces: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    _src_file: Mapped[str] = mapped_column(Text, nullable=False)
    _src_sheet: Mapped[str] = mapped_column(Text, nullable=False)

    product: Mapped["ProductDimension | None"] = relationship()


class SellOutFact(Base):
    """Del Monte only (DEC-03) — category grain, from Sell Out files'
    '/ACE/BASE'-style hierarchy paths. Honest ceiling for Del Monte
    forecasting — do not join a fabricated per-SKU allocation here."""
    __tablename__ = "sellout_fact"
    __table_args__ = (
        CheckConstraint("principal = 'delmonte'", name="ck_sellout_fact_principal"),
        UniqueConstraint("category_path", "region", "_period", name="uq_sellout_fact_natural_key"),
        Index("ix_sellout_fact_period", "_period"),
    )

    sellout_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_key: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_dimension.product_key"))
    category_path: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. '/ACE/BASE'
    principal: Mapped[str] = mapped_column(Text, nullable=False, default="delmonte")
    region: Mapped[str | None] = mapped_column(Text)
    _period: Mapped[str] = mapped_column(Text, nullable=False)      # 'YYYY-MM'
    quantity: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))  # negatives are real, never clamped
    net_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    _src_file: Mapped[str] = mapped_column(Text, nullable=False)
    _src_sheet: Mapped[str] = mapped_column(Text, nullable=False)

    product: Mapped["ProductDimension | None"] = relationship()


class UnileverSkuDemandFact(Base):
    """Unilever only (DEC-03) — the SOLE confirmed SKU-level demand
    source in the whole corpus (the La Union MHTML file). Distinct grain
    from SalesFact (Calendar Month x Product x Pack Size, not an
    invoice), which is why it's its own table rather than a nullable
    product_key bolted onto SalesFact. Direct SARIMA input for Unilever."""
    __tablename__ = "unilever_sku_demand_fact"
    __table_args__ = (
        UniqueConstraint("sku_code", "calendar_month", name="uq_unilever_sku_demand_fact_natural_key"),
        Index("ix_unilever_sku_demand_product", "product_key"),
    )

    demand_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_key: Mapped[int] = mapped_column(BigInteger, ForeignKey("product_dimension.product_key"), nullable=False)
    sku_code: Mapped[str] = mapped_column(Text, nullable=False)
    calendar_month: Mapped[str] = mapped_column(Text, nullable=False)  # 'YYYY-MM', from the row's own source cell
    region: Mapped[str] = mapped_column(Text, nullable=False, default="la_union")
    # DEC-11: in pieces — set from the source's reported
    # sale_quantity_pieces column, not derived from sale_quantity_cases x
    # pack_size (only ~84% consistent with reported pieces on real data;
    # see schema.sql for the full note).
    quantity_sold: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    # Added 2026-08: classify_abc() needs total_revenue per SKU; this is
    # the only Unilever SKU-grain fact table. See schema.sql's comment.
    net_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    _src_file: Mapped[str] = mapped_column(Text, nullable=False)
    _src_sheet: Mapped[str] = mapped_column(Text, nullable=False)

    product: Mapped["ProductDimension"] = relationship()


# ============================================================
# SECTION 4 — ANALYTICS OUTPUTS (written by analytics/ pipeline,
# read-only from backend/'s point of view — architecture boundary)
# ============================================================

class ABCClassification(Base):
    """product_key is always a grain='sku' (Unilever) or grain='category'
    (Del Monte) row — never a fabricated one-size-fits-all key."""
    __tablename__ = "abc_classification"
    __table_args__ = (
        CheckConstraint("principal IN ('unilever', 'delmonte')", name="ck_abc_classification_principal"),
        CheckConstraint("tier IN ('A', 'B', 'C')", name="ck_abc_classification_tier"),
        # t12m_new added by migration 0044 (DEC-38, the Unilever Tier A basis).
        CheckConstraint("method IN ('single', 't3m', 't12m_new')", name="ck_abc_classification_method"),
        # Widened by migration 0017: 'single' and 't3m' legitimately coexist for
        # the same (product_key, classification_period), so the pre-0017
        # two-column key no longer describes the live table. Constraint name
        # matches what 0017 actually created, not the old 'uq_...' convention.
        UniqueConstraint(
            "product_key", "classification_period", "method",
            name="abc_classification_product_key_period_method_key",
        ),
        Index("ix_abc_classification_tier", "tier", "classification_period"),
    )

    classification_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_key: Mapped[int] = mapped_column(BigInteger, ForeignKey("product_dimension.product_key"), nullable=False)
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    classification_period: Mapped[str] = mapped_column(Text, nullable=False)  # 'YYYY-MM'
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    revenue_share: Mapped[decimal.Decimal | None] = mapped_column(Numeric(7, 4))
    cumulative_share: Mapped[decimal.Decimal | None] = mapped_column(Numeric(7, 4))
    # boundary_flag: migration 0002. method/run_id: migration 0017. All three
    # were live in the DB but absent from this model.
    boundary_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'single'"))
    run_id: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'legacy_pre_0017'"))
    # added_as_new: migration 0044. True on a row made Class A by the t12m_new
    # new-product rule rather than by the 12-month 80% cut.
    added_as_new: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    computed_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped["ProductDimension"] = relationship()


class ForecastResult(Base):
    """Tier A, Unilever SKU grain (DEC-03). The LP gates on mase <
    analytics.params.MASE_GATE (scripts/run_lp.py), never on mape."""
    __tablename__ = "forecast_result"
    __table_args__ = (
        UniqueConstraint("product_key", "forecast_date", name="uq_forecast_result_natural_key"),
        Index("ix_forecast_result_product", "product_key"),
    )

    forecast_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_key: Mapped[int] = mapped_column(BigInteger, ForeignKey("product_dimension.product_key"), nullable=False)
    forecast_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    forecast_value: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    confidence_lower: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    confidence_upper: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    mape: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 3))  # schema.sql and live: NUMERIC(10,3); percent; reported, never a gate (the LP gates on mase)
    model_params: Mapped[dict | None] = mapped_column(JSONB)             # SARIMA order etc., stored as given
    generated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped["ProductDimension"] = relationship()


class LPRecommendation(Base):
    """SS_i = Z x sigma (Z=1.28, 90% service level); rop_i holds the
    order-up-to TARGET stock T_i (scripts/run_lp.py), not a reorder point;
    Q_i from the LP (weights analytics.params.LP_WEIGHTS).
    status supports the dashboard's Accept/Dismiss write-back (Phase 7)."""
    __tablename__ = "lp_recommendation"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'dismissed')", name="ck_lp_recommendation_status"),
        UniqueConstraint("product_key", "planning_cycle_date", name="uq_lp_recommendation_natural_key"),
        Index("ix_lp_recommendation_status", "status", "planning_cycle_date"),
    )

    recommendation_key: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_key: Mapped[int] = mapped_column(BigInteger, ForeignKey("product_dimension.product_key"), nullable=False)
    planning_cycle_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    q_i: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    rop_i: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    ss_i: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    decided_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped["ProductDimension"] = relationship()


# ============================================================
# NOTE — BO_Monitoring_View (schema.sql §5) is intentionally NOT mapped
# here. It's a plain SQL view (Purchase_Fact + SalesReturn_Fact grouped
# by principal/region/period), not a table, and its shape is flagged as
# an open question pending confirmation with Yuan (see schema.sql's
# comment block). Query it directly with `select()` against a
# `Table("bo_monitoring_view", ..., autoload_with=engine)` from the
# router once that question is resolved — mapping it to a fake ORM
# class now would lock in an unconfirmed contract.
#
# Same reasoning applies to Product_Demand_View (schema.sql §7, DEC-13) —
# a plain SQL view unifying Unilever_SKU_Demand_Fact + SellOut_Fact into
# one read shape for downstream models (ABC/SARIMA/LP), not itself a
# table. No consumer reads from it yet (analytics/ hasn't run against a
# live DB) - query it via `Table("product_demand_view", ...,
# autoload_with=engine)` once one does, rather than locking in an ORM
# class ahead of any real usage.
# ============================================================
