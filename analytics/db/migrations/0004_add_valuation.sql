-- 0004_add_valuation.sql
-- Add missing valuation column to Inventory_Fact for dashboard KPI calculations

ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS valuation NUMERIC;

-- Recreate the view to include the new column
CREATE OR REPLACE VIEW Inventory_Fact_Real AS
SELECT * FROM Inventory_Fact WHERE is_demo = false;
