# OpsDetect — Operations Data Quality & Review Dashboard

A local portfolio prototype for reviewing operational CSV data. It uses Python Flask, SQLite, and vanilla JavaScript.

## Features
- CSV import (up to 5,000 rows / 3 MB) with schema validation and atomic replacement
- Flags duplicate references, missing fields, and amount outliers (3x median heuristic)
- Flags purchase orders overdue **only when an explicit `due_date` exists** and status is not complete
- SQLite persistence for records, findings, review status, notes and audit history
- Export findings as CSV, and local health endpoint
- Synthetic sample dataset and automated test suite

## Quick start
```bash
py -m pip install -r requirements.txt
py app.py
```
Open http://127.0.0.1:5000 and select **Load sample data**. On macOS/Linux, use `python3` instead of `py`.

## Tests
```bash
py -m unittest discover -s tests -v
```

## CSV format
Required headers: `id,type,vendor,amount,date,reference,status`; optional: `due_date`. Dates must be `YYYY-MM-DD`. See `sample_data.csv`.

## Important limitations
- Local single-user portfolio prototype, **not production-ready**: no authentication, roles, deployment hardening or enterprise integrations.
- Import replaces the dataset **and clears review history**. Export review data first if needed.
- Duplicate-reference and outlier rules are heuristics for human review, **not fraud detection or proof of financial loss**.
- The `due_date` field is required to make an overdue determination; an old order date alone is insufficient.
- Use synthetic or explicitly authorized data only.
- No claimed savings, accuracy, or real-company deployment.
