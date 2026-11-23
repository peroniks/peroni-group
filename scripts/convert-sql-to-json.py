#!/usr/bin/env python3
"""
MTC SQL-to-JSON Converter
Converts raw QCDB MySQL dump into public canonical MTC JSON dataset.
Usage:
    python scripts/convert-sql-to-json.py [sql_file_path] [output_json_path]
"""

import sys
import os
import re
import json
import sqlite3
import time
from datetime import datetime

DEFAULT_SQL_PATH = r"C:\laragon\www\peroni-group\data-sql\database mc.sql"
DEFAULT_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "certificates-demo.json")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def format_date(d_str):
    if not d_str or str(d_str) == "NULL":
        return "N/A"
    try:
        s = str(d_str).split(".")[0].strip()
        if " " in s:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        else:
            dt = datetime.strptime(s, "%Y-%m-%d")
        return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"
    except Exception:
        return str(d_str)

def format_chem(val, decimals=2):
    if val is not None and str(val) != "NULL" and str(val) != "":
        try:
            f = float(val)
            return f"{f:.{decimals}f}%"
        except (ValueError, TypeError):
            return None
    return None

def convert(sql_path=DEFAULT_SQL_PATH, output_path=DEFAULT_OUTPUT_PATH):
    print(f"[*] Starting MTC SQL to JSON conversion...")
    print(f"[*] Source SQL: {sql_path}")
    print(f"[*] Target JSON: {output_path}")

    if not os.path.exists(sql_path):
        raise FileNotFoundError(f"Source SQL file not found: {sql_path}")

    t0 = time.time()
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE samples (
        id INTEGER PRIMARY KEY, report_no TEXT, heat_no TEXT, batch_no TEXT, po_customer TEXT,
        grade TEXT, standard TEXT, product_type TEXT, size_spec TEXT, po_no TEXT, customer TEXT,
        process TEXT, test_date TEXT, machine_spektro TEXT, machine_tensile TEXT, machine_hardness TEXT,
        overall_result TEXT, status TEXT, created_by INTEGER, approved_by INTEGER, approved_at TEXT,
        version INTEGER, created_at TEXT, updated_at TEXT, deleted_at TEXT
    );
    CREATE TABLE tensile_tests (
        id INTEGER PRIMARY KEY, sample_id INTEGER, ys_mpa REAL, uts_mpa REAL, elong_pct REAL,
        ra_pct REAL, method_std TEXT, specimen_dims TEXT, pass_bool INTEGER, remarks TEXT,
        created_at TEXT, updated_at TEXT, deleted_at TEXT
    );
    CREATE TABLE hardness_tests (
        id INTEGER PRIMARY KEY, sample_id INTEGER, method TEXT, scale TEXT, load_kgf REAL,
        location1 REAL, location2 REAL, location3 REAL, avg_value REAL, pass_bool INTEGER, remarks TEXT,
        created_at TEXT, updated_at TEXT, deleted_at TEXT
    );
    CREATE TABLE spectro_results (
        id INTEGER PRIMARY KEY, sample_id INTEGER,
        c REAL, si REAL, mn REAL, p REAL, s REAL, cr REAL, ni REAL, mo REAL, cu REAL, n REAL,
        al REAL, v REAL, co REAL, ti REAL, nb REAL, w REAL, fe REAL,
        pass_bool INTEGER, remarks TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT
    );
    """)

    target_tables = {"samples", "tensile_tests", "hardness_tests", "spectro_results"}
    current_stmt = []
    in_insert = False
    insert_count = 0

    with open(sql_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("INSERT INTO `"):
                m = re.match(r"INSERT INTO `(\w+)`", line)
                if m and m.group(1) in target_tables:
                    in_insert = True
                    current_stmt = [line]
                else:
                    in_insert = False
            elif in_insert:
                current_stmt.append(line)
                if line.rstrip().endswith(";"):
                    stmt = "".join(current_stmt)
                    cur.execute(stmt)
                    insert_count += 1
                    in_insert = False
                    current_stmt = []

    conn.commit()
    t_load = time.time()
    print(f"[*] Imported {insert_count} relevant table statements into in-memory database in {t_load - t0:.2f}s")

    # Canonical extraction query (APPROVED only, non-deleted, with valid mechanical and chemical test data)
    query = """
    SELECT 
      s.heat_no AS heatNumber, 
      s.report_no AS certificateNumber, 
      s.grade AS materialGrade, 
      s.standard AS specification, 
      t.ys_mpa AS yieldStrength, 
      t.uts_mpa AS tensileStrength, 
      h.avg_value AS hardness, 
      s.status AS approvalStatus, 
      s.test_date AS testDate, 
      s.approved_at AS approvedAt, 
      sp.c, sp.si, sp.mn, sp.p, sp.s, sp.cr, sp.ni, sp.mo, sp.cu, sp.n, sp.al, sp.v, sp.co, sp.ti, sp.nb, sp.w, sp.fe 
    FROM samples s 
    JOIN tensile_tests t ON t.sample_id = s.id AND t.deleted_at IS NULL 
    JOIN hardness_tests h ON h.sample_id = s.id AND h.deleted_at IS NULL 
    JOIN spectro_results sp ON sp.sample_id = s.id AND sp.deleted_at IS NULL 
    WHERE s.status = 'APPROVED' 
      AND s.deleted_at IS NULL 
      AND s.heat_no IS NOT NULL 
      AND s.heat_no != '' 
      AND s.report_no IS NOT NULL 
      AND s.report_no != '' 
      AND t.ys_mpa IS NOT NULL 
      AND t.uts_mpa IS NOT NULL 
      AND h.avg_value IS NOT NULL 
      AND sp.cr IS NOT NULL
    ORDER BY s.id ASC;
    """

    cur.execute(query)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"[*] Extracted {len(rows)} verified certificates.")

    formatted_records = []
    for r in rows:
        row = dict(zip(cols, r))

        chem = {}
        for elem, dec in [
            ("c", 3), ("si", 2), ("mn", 2), ("p", 3), ("s", 3),
            ("cr", 2), ("ni", 2), ("mo", 2), ("cu", 2), ("n", 3),
            ("al", 3), ("v", 3), ("co", 3), ("ti", 3), ("nb", 3),
            ("w", 3), ("fe", 2)
        ]:
            val_str = format_chem(row.get(elem), dec)
            if val_str:
                chem[elem] = val_str

        ys = f"{float(row['yieldStrength']):.2f} MPa" if row['yieldStrength'] is not None else "N/A"
        uts = f"{float(row['tensileStrength']):.2f} MPa" if row['tensileStrength'] is not None else "N/A"
        hard = f"{float(row['hardness']):.2f} HB" if row['hardness'] is not None else "N/A"

        rec = {
            "heatNumber": str(row["heatNumber"]).strip(),
            "certificateNumber": str(row["certificateNumber"]).strip(),
            "materialGrade": str(row["materialGrade"]).strip() if row["materialGrade"] else "N/A",
            "specification": str(row["specification"]).strip() if row["specification"] else "N/A",
            "yieldStrength": ys,
            "tensileStrength": uts,
            "hardness": hard,
            "approvalStatus": str(row["approvalStatus"]).strip(),
            "manufacturingDate": format_date(row["testDate"]),
            "verificationDate": format_date(row["approvedAt"]),
            "chemicalComposition": chem
        }
        formatted_records.append(rec)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    temp_path = output_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as out_f:
            json.dump(formatted_records, out_f, indent=2, ensure_ascii=False)
        # Atomic replace to ensure production dataset is never corrupted on failure
        os.replace(temp_path, output_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        print(f"[-] ERROR: Conversion failed, production dataset was NOT touched: {e}")
        raise

    t_end = time.time()
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[+] SUCCESS: Exported {len(formatted_records)} records to {output_path} ({size_mb:.2f} MB) in {t_end - t0:.2f}s")
    return len(formatted_records)

if __name__ == "__main__":
    sql_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SQL_PATH
    out_arg = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT_PATH
    convert(sql_arg, out_arg)
