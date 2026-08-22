"""SSM ETL discovery/profiling tools.

Made importable (`from profiling.reader import read_workbook`, etc.) so the
Extract stage (analytics/etl/extract/) can reuse the format-sniffing and
detection primitives here instead of duplicating them.
"""
