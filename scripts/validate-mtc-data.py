#!/usr/bin/env python3
"""
MTC Dataset Pre-Publishing Validator
Validates public MTC JSON dataset before deployment or commit.
Usage:
    python scripts/validate-mtc-data.py [json_file_path]
"""

import sys
import os
import json
import re
import subprocess

DEFAULT_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "certificates-demo.json")
REPO_DIR = os.path.join(os.path.dirname(__file__), "..")

BENCHMARK_HEAT = "A204102609"
BENCHMARK_EXPECTED = {
    "certificateNumber": "QC/2026/10/101",
    "materialGrade": "1.4308",
    "specification": "BS EN 10213",
    "yieldStrength": "251.86 MPa",
    "tensileStrength": "502.91 MPa",
    "hardness": "168.00 HB",
    "approvalStatus": "APPROVED",
    "cr": "18.26%",
    "ni": "8.16%"
}

# Strict Whitelist: Only these root fields are permitted in the public dataset
ALLOWED_ROOT_KEYS = {
    "heatNumber",
    "certificateNumber",
    "materialGrade",
    "specification",
    "yieldStrength",
    "tensileStrength",
    "hardness",
    "approvalStatus",
    "manufacturingDate",
    "verificationDate",
    "chemicalComposition"
}

# Mandatory Root Fields that must not be null/empty
REQUIRED_ROOT_KEYS = [
    "heatNumber",
    "certificateNumber",
    "materialGrade",
    "specification",
    "yieldStrength",
    "tensileStrength",
    "hardness",
    "approvalStatus",
    "manufacturingDate",
    "verificationDate",
    "chemicalComposition"
]

# Strict Whitelist: Only recognized metallurgical elements permitted in chemicalComposition
ALLOWED_CHEM_KEYS = {
    "c", "si", "mn", "p", "s", "cr", "ni", "mo", "cu", "n",
    "al", "v", "co", "ti", "nb", "w", "fe"
}

FORBIDDEN_KEYS = {
    "customer", "po_no", "po_customer", "price", "pricing", "cost", "margin",
    "password", "email", "remember_token", "user", "user_id", "users",
    "phone", "address", "company_internal", "ip_address", "client_ip"
}

def validate(json_path=DEFAULT_JSON_PATH):
    print("=" * 70)
    print("MTC DATASET PRE-PUBLISHING AUDIT & VALIDATION")
    print("=" * 70)
    print(f"Target JSON File: {json_path}\n")

    results = []

    # 1. File existence and JSON Parsing
    if not os.path.exists(json_path):
        results.append(("1. File Existence", "FAIL", f"File not found: {json_path}"))
        print_report(results)
        return False

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        results.append(("1. JSON Parsing", "PASS", f"Valid JSON, parsed successfully"))
    except Exception as e:
        results.append(("1. JSON Parsing", "FAIL", f"Invalid JSON syntax: {e}"))
        print_report(results)
        return False

    if not isinstance(data, list):
        results.append(("2. Data Structure", "FAIL", "Root element must be a JSON array"))
        print_report(results)
        return False

    # 2. Record count threshold
    count = len(data)
    if count >= 3000:
        results.append(("2. Record Count", "PASS", f"{count} records found (>= 3,000 threshold)"))
    else:
        results.append(("2. Record Count", "FAIL", f"Suspiciously low record count: {count}"))

    # 3. Required Fields & Schema Integrity
    missing_fields_count = 0
    non_approved_count = 0
    unit_mismatch_count = 0

    cert_numbers = set()
    cert_duplicates = 0

    unknown_root_keys = set()
    unknown_chem_keys = set()

    for idx, r in enumerate(data):
        # Strict Root Allowlist Check
        r_keys = set(r.keys())
        diff_root = r_keys - ALLOWED_ROOT_KEYS
        if diff_root:
            unknown_root_keys.update(diff_root)

        # Strict Chemical Allowlist Check
        chem = r.get("chemicalComposition")
        if isinstance(chem, dict):
            diff_chem = set(chem.keys()) - ALLOWED_CHEM_KEYS
            if diff_chem:
                unknown_chem_keys.update(diff_chem)
        elif chem is not None:
            unknown_chem_keys.add("invalid_non_dict_type")

        # Check required fields
        for rf in REQUIRED_ROOT_KEYS:
            if rf not in r or r[rf] is None or r[rf] == "":
                missing_fields_count += 1

        # Check approval status
        if r.get("approvalStatus") != "APPROVED":
            non_approved_count += 1

        # Check unit formatting
        ys = r.get("yieldStrength", "")
        uts = r.get("tensileStrength", "")
        hd = r.get("hardness", "")
        if (ys != "N/A" and not ys.endswith(" MPa")) or \
           (uts != "N/A" and not uts.endswith(" MPa")) or \
           (hd != "N/A" and not hd.endswith(" HB")):
            unit_mismatch_count += 1

        # Certificate number uniqueness
        c_num = str(r.get("certificateNumber", "")).strip().lower()
        if c_num in cert_numbers:
            cert_duplicates += 1
        else:
            cert_numbers.add(c_num)

    # 3A. Schema Allowlist Check
    if len(unknown_root_keys) == 0 and len(unknown_chem_keys) == 0:
        results.append(("3A. Schema Allowlist", "PASS", "100% records conform strictly to allowed root and chemical fields"))
    else:
        err_msg = []
        if unknown_root_keys:
            err_msg.append(f"Foreign root fields: {sorted(list(unknown_root_keys))}")
        if unknown_chem_keys:
            err_msg.append(f"Foreign chem fields: {sorted(list(unknown_chem_keys))}")
        results.append(("3A. Schema Allowlist", "FAIL", " | ".join(err_msg)))

    # 3B. Required Fields Check
    if missing_fields_count == 0:
        results.append(("3B. Required Fields", "PASS", "All required fields present and non-empty across all records"))
    else:
        results.append(("3B. Required Fields", "FAIL", f"{missing_fields_count} missing field occurrences"))

    if non_approved_count == 0:
        results.append(("4. Approval Status", "PASS", "All records have status = 'APPROVED'"))
    else:
        results.append(("4. Approval Status", "FAIL", f"{non_approved_count} non-approved records found"))

    if unit_mismatch_count == 0:
        results.append(("5. Unit Standard", "PASS", "Engineering units formatted correctly (MPa, HB)"))
    else:
        results.append(("5. Unit Standard", "FAIL", f"{unit_mismatch_count} records with invalid unit suffixes"))

    # 4. Certificate uniqueness
    if cert_duplicates == 0:
        results.append(("6. Certificate Uniqueness", "PASS", f"{len(cert_numbers)} certificates, 0 duplicates"))
    else:
        results.append(("6. Certificate Uniqueness", "FAIL", f"{cert_duplicates} duplicate certificate numbers detected!"))

    # 5. PII & Commercial Leak Detection across 100% of dataset
    leaked_keys = set()
    def check_keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in FORBIDDEN_KEYS:
                    leaked_keys.add(k)
                check_keys(v)
        elif isinstance(obj, list):
            for item in obj:
                check_keys(item)

    for r in data:
        check_keys(r)

    if len(leaked_keys) == 0:
        results.append(("7. PII / Data Privacy", "PASS", "Zero customer names, POs, pricing, or internal PII keys"))
    else:
        results.append(("7. PII / Data Privacy", "FAIL", f"Forbidden sensitive keys detected: {leaked_keys}"))

    # 6. Benchmark Verification (Heat: A204102609)
    benchmark_rec = next((r for r in data if r.get("heatNumber") == BENCHMARK_HEAT), None)
    if benchmark_rec:
        chem = benchmark_rec.get("chemicalComposition", {})
        mismatches = []
        for k, exp in BENCHMARK_EXPECTED.items():
            if k in ["cr", "ni"]:
                actual = chem.get(k)
            else:
                actual = benchmark_rec.get(k)
            if actual != exp:
                mismatches.append(f"{k}: expected {exp}, got {actual}")

        if not mismatches:
            results.append(("8. Benchmark Heat A204102609", "PASS", f"All verified traits match QC/2026/10/101 exactly"))
        else:
            results.append(("8. Benchmark Heat A204102609", "FAIL", f"Mismatches: {'; '.join(mismatches)}"))
    else:
        results.append(("8. Benchmark Heat A204102609", "FAIL", f"Benchmark heat {BENCHMARK_HEAT} not found in dataset!"))

    # 7. Git Security Check (No SQL tracked or staged)
    try:
        git_check = subprocess.run(
            ["git", "ls-files", "*.sql", "*.SQL"],
            cwd=REPO_DIR, capture_output=True, text=True, check=True
        )
        tracked_sql = git_check.stdout.strip()
        if not tracked_sql:
            results.append(("9. Git SQL Security", "PASS", "No SQL files tracked in Git repository"))
        else:
            results.append(("9. Git SQL Security", "FAIL", f"SQL files tracked in Git: {tracked_sql}"))
    except Exception as e:
        results.append(("9. Git SQL Security", "WARN", f"Could not verify git tracking: {e}"))

    passed = print_report(results)
    return passed

def print_report(results):
    print(f"{'CHECK ITEM':<32} | {'STATUS':<6} | {'DETAILS'}")
    print("-" * 75)
    all_pass = True
    for item, status, detail in results:
        if status == "FAIL":
            all_pass = False
        print(f"{item:<32} | {status:<6} | {detail}")
    print("-" * 75)

    if all_pass:
        print("[+] FINAL RESULT: ALL CHECKS PASSED. Dataset is READY for publication.")
    else:
        print("[-] FINAL RESULT: VALIDATION FAILED. DO NOT PUBLISH OR DEPLOY.")
    print("=" * 70 + "\n")
    return all_pass

if __name__ == "__main__":
    path_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON_PATH
    ok = validate(path_arg)
    sys.exit(0 if ok else 1)
