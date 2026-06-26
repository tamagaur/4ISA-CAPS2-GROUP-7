"""
analytics.db.models — SQLAlchemy ORM table definitions.

Phase 3A (CLAUDE.md Step 2 — Checkpoint: DDL matches Section 3.3.1 and 3.3.2):
  Dimension tables (no FK dependencies):
    Product_Dimension, Date_Dimension, Supplier_Dimension,
    Customer_Dimension, Salesman_Dimension
  Fact tables (reference dimensions):
    Sales_Fact, Inventory_Fact, Purchase_Fact, SellOut_Fact, SalesReturn_Fact
  Derived/ML output:
    ABC_Classification

Yuan must review all table definitions against the Galaxy Schema ERD before
any CREATE TABLE statement is executed.

TODO: Define all Table/mapped_class objects using SQLAlchemy 2.0 DeclarativeBase.
      Mirror schema.sql exactly — do not diverge.
"""
