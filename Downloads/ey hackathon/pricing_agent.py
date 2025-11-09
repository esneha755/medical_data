# (paste the full pricing_agent.py code provided earlier)
# For convenience, here's a compact version — copy all of this into pricing_agent.py
import argparse, json, os, pandas as pd
from difflib import get_close_matches

PL_PERCENT = 0.02
CONTINGENCY_PERCENT = 0.03
MARGIN_PERCENT = 0.10
GST_PERCENT = 0.18
FALLBACK_SIMILARITY_CUTOFF = 0.6

DEFAULT_TECH_CSV = "technical_output.csv"
DEFAULT_PRODUCT_CSV = "product_price.csv"
DEFAULT_TEST_CSV = "test_price.csv"
DEFAULT_OUT_DIR = "pricing_outputs"

def load_csv(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV not found: {path}")
    return pd.read_csv(path)

def parse_tests_field(tests_field):
    if pd.isna(tests_field) or str(tests_field).strip() == "":
        return []
    s = str(tests_field).strip()
    if "|" in s:
        parts = [t.strip() for t in s.split("|") if t.strip()]
    elif "," in s:
        parts = [t.strip() for t in s.split(",") if t.strip()]
    else:
        parts = [s]
    return parts

def lookup_base_price(product_df, sku):
    row = product_df.loc[product_df["product_sku"] == sku]
    if row.empty:
        return None
    return float(row["base_price_per_unit"].iloc[0])

def fallback_nearest_sku(product_df, sku):
    candidates = list(product_df["product_sku"].astype(str).unique()) + list(product_df.get("product_name", pd.Series([])).astype(str).unique())
    matches = get_close_matches(sku, candidates, n=3, cutoff=FALLBACK_SIMILARITY_CUTOFF)
    return matches

def compute_test_costs(test_df, tests, qty):
    per_unit = 0.0
    per_job = 0.0
    unknown = []
    for t in tests:
        row = test_df.loc[test_df["test_code"] == t]
        if row.empty:
            unknown.append(t)
            continue
        r = row.iloc[0]
        ctype = str(r["cost_type"]).strip()
        cval = float(r["cost_value"])
        if ctype == "per_unit":
            per_unit += cval
        elif ctype == "per_job":
            per_job += cval
        else:
            unknown.append(t)
    per_unit_from_job = per_job / max(qty, 1)
    return {"per_unit": per_unit + per_unit_from_job, "per_job_total": per_job, "unknown": unknown}

def round2(x):
    return round(float(x) + 1e-9, 2)

def price_line_item(sku, qty, tests, product_df, test_df, pl_percent=PL_PERCENT, contingency_percent=CONTINGENCY_PERCENT, margin_percent=MARGIN_PERCENT, gst_percent=GST_PERCENT):
    bup = lookup_base_price(product_df, sku)
    fallback = []
    if bup is None:
        fallback = fallback_nearest_sku(product_df, sku)
        return {"error": f"SKU_NOT_FOUND::{sku}", "fallback_candidates": fallback}
    test_info = compute_test_costs(test_df, tests, qty)
    test_per_unit = test_info["per_unit"]
    test_per_job_total = test_info["per_job_total"]
    unknown_tests = test_info["unknown"]

    pl = pl_percent * bup
    contingency = contingency_percent * (bup + test_per_unit + pl)
    pre_tax = bup + test_per_unit + pl + contingency
    margin_amt = pre_tax * margin_percent
    taxable = pre_tax + margin_amt
    tax_amt = taxable * gst_percent
    final_unit_price = pre_tax + margin_amt + tax_amt
    total_line = final_unit_price * qty

    return {
        "product_sku": sku,
        "quantity": int(qty),
        "base_price_per_unit": round2(bup),
        "test_cost_per_unit": round2(test_per_unit),
        "test_cost_per_job_total": round2(test_per_job_total),
        "packing_logistics_per_unit": round2(pl),
        "contingency_per_unit": round2(contingency),
        "pre_tax_per_unit": round2(pre_tax),
        "margin_per_unit": round2(margin_amt),
        "tax_per_unit": round2(tax_amt),
        "final_unit_price": round2(final_unit_price),
        "total_price_for_line": round2(total_line),
        "unknown_tests": "|".join(unknown_tests) if unknown_tests else "",
        "fallback_candidates": "|".join(fallback) if fallback else ""
    }

def run_pricing(tech_csv, product_csv, test_csv, out_dir, pl_percent=PL_PERCENT, contingency_percent=CONTINGENCY_PERCENT, margin_percent=MARGIN_PERCENT, gst_percent=GST_PERCENT):
    os.makedirs(out_dir, exist_ok=True)
    tech_df = load_csv(tech_csv)
    product_df = load_csv(product_csv)
    test_df = load_csv(test_csv)

    results = []
    errors = []
    for _, row in tech_df.iterrows():
        rfp_item = row.get("rfp_item", "")
        sku = str(row.get("recommended_sku", "")).strip()
        qty = int(row.get("quantity", 1))
        tests = parse_tests_field(row.get("tests_required", ""))
        res = price_line_item(sku, qty, tests, product_df, test_df, pl_percent=pl_percent, contingency_percent=contingency_percent, margin_percent=margin_percent, gst_percent=gst_percent)
        if "error" in res:
            errors.append({"rfp_item": rfp_item, "error": res["error"], "fallback": res.get("fallback_candidates","")})
            results.append({
                "rfp_item": rfp_item,
                "product_sku": sku,
                "quantity": qty,
                "error": res["error"],
                "fallback_candidates": res.get("fallback_candidates", "")
            })
            continue
        res.update({"rfp_item": rfp_item, "tests_required": "|".join(tests)})
        results.append(res)

    out_df = pd.DataFrame(results)
    cols = ["rfp_item","product_sku","quantity","base_price_per_unit","test_cost_per_unit","packing_logistics_per_unit","contingency_per_unit","pre_tax_per_unit","margin_per_unit","tax_per_unit","final_unit_price","total_price_for_line","test_cost_per_job_total","tests_required","unknown_tests","fallback_candidates","error"]
    cols_existing = [c for c in cols if c in out_df.columns]
    out_df = out_df[cols_existing]

    csv_path = os.path.join(out_dir, "pricing_table.csv")
    json_path = os.path.join(out_dir, "pricing_summary.json")
    out_df.to_csv(csv_path, index=False)

    aggregates = {
        "subtotal_material_value": round2((out_df.get("base_price_per_unit",0) * out_df.get("quantity",0)).sum()),
        "subtotal_tests_allocated_per_unit_sum": round2((out_df.get("test_cost_per_unit",0) * out_df.get("quantity",0)).sum()),
        "subtotal_tests_per_job_total": round2(out_df.get("test_cost_per_job_total",0).sum()),
        "grand_total_price": round2(out_df.get("total_price_for_line",0).sum())
    }
    summary = {"pricing_table_rows": len(out_df), "aggregates": aggregates, "errors": errors, "pricing_table_csv": csv_path}
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    return out_df, summary

def build_arg_parser():
    p = argparse.ArgumentParser(description="Pricing Agent for RFPs")
    p.add_argument("--tech", default=DEFAULT_TECH_CSV, help="technical_output.csv path")
    p.add_argument("--products", default=DEFAULT_PRODUCT_CSV, help="product_price.csv path")
    p.add_argument("--tests", default=DEFAULT_TEST_CSV, help="test_price.csv path")
    p.add_argument("--out", default=DEFAULT_OUT_DIR, help="output directory")
    p.add_argument("--pl", type=float, default=PL_PERCENT, help="packing & logistics percent (e.g., 0.02)")
    p.add_argument("--contingency", type=float, default=CONTINGENCY_PERCENT, help="contingency percent")
    p.add_argument("--margin", type=float, default=MARGIN_PERCENT, help="margin percent")
    p.add_argument("--gst", type=float, default=GST_PERCENT, help="gst percent")
    return p

def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    df, summary = run_pricing(args.tech, args.products, args.tests, args.out, pl_percent=args.pl, contingency_percent=args.contingency, margin_percent=args.margin, gst_percent=args.gst)
    print("Pricing finished. Summary:")
    print(json.dumps(summary, indent=2))
    print(f"CSV written to: {summary['pricing_table_csv']}")

if __name__ == "__main__":
    main()
