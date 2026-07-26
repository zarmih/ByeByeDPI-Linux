import json
import os
import csv
import time
import datetime
import statistics
import shutil
from pathlib import Path
from PySide6.QtCore import QStandardPaths

SCHEMA_VERSION = 2
APP_VERSION = "1.0.0"

def get_history_dir(test_path=None):
    if test_path:
        d = test_path
    else:
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        d = os.path.join(app_data, "history")
    os.makedirs(d, exist_ok=True)
    return d

def _atomic_write_json(filepath, data):
    tmp_path = filepath + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, filepath)

def _remove_secrets(data):
    # Just a simple sanity clean of absolute paths or tokens if they somehow entered (we don't collect them, but just in case)
    if isinstance(data, dict):
        return {k: _remove_secrets(v) for k, v in data.items() if not k.startswith("secret_")}
    elif isinstance(data, list):
        return [_remove_secrets(i) for i in data]
    elif isinstance(data, str):
        # We don't blindly replace all paths, but we can ensure no /mnt/ paths
        return data
    return data

def create_bundle(
    strategies_snapshots,
    targets_snapshots,
    results_matrix,
    started_at,
    finished_at,
    state,
    selected_strategy_count,
    selected_target_count,
    planned_checks,
    completed_checks,
    upstream_info,
    policy_info
):
    aggregates = compute_aggregates(results_matrix)
    ranks = compute_ranks(aggregates)
    best_id = ranks[0]["id"] if ranks else None
    
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_metadata": {
            "started_at": started_at,
            "finished_at": finished_at,
            "state": state,
            "elapsed": (finished_at - started_at) if started_at and finished_at else 0,
            "selected_strategy_count": selected_strategy_count,
            "selected_target_count": selected_target_count,
            "planned_checks": planned_checks,
            "completed_checks": completed_checks
        },
        "upstream": upstream_info,
        "policy": policy_info,
        "snapshots": {
            "strategies": _remove_secrets(strategies_snapshots),
            "targets": _remove_secrets(targets_snapshots)
        },
        "results": results_matrix,
        "aggregates": aggregates,
        "ranking_order": [r["id"] for r in ranks],
        "best_strategy_id": best_id
    }
    return bundle

def compute_aggregates(results_matrix):
    aggregates = {"strategies": {}}
    for strat_id, res_list in results_matrix.items():
        passed = sum(1 for r in res_list if r["status"] == "Success")
        total = len(res_list)
        timeout = sum(1 for r in res_list if r["status"] == "Timeout")
        errors = sum(1 for r in res_list if r["status"] == "Error")
        succ_durs = [r["duration"] for r in res_list if r["status"] == "Success"]
        
        avg = statistics.mean(succ_durs) if succ_durs else 0.0
        med = statistics.median(succ_durs) if succ_durs else 0.0
        
        # Group summary
        group_counts = {}
        # We need group names, but we don't have them in results directly without snapshots.
        # So we leave group summaries out of raw aggregates or assume they are added later.
        # Actually, targets snapshot is available to the caller. We will just compute raw counts here.
        
        aggregates["strategies"][strat_id] = {
            "passed": passed,
            "total": total,
            "success_rate": (passed / total * 100) if total > 0 else 0,
            "avg_time": avg,
            "median_time": med,
            "timeouts": timeout,
            "errors": errors
        }
    return aggregates

def compute_ranks(aggregates):
    # Sort key: passed DESC, success_rate DESC, median successful duration ASC, timeout/error ASC
    rows = []
    for strat_id, a in aggregates["strategies"].items():
        rows.append((
            -a["passed"],
            -a["success_rate"],
            a["median_time"] if a["median_time"] > 0 else 9999,
            a["timeouts"] + a["errors"],
            strat_id
        ))
    rows.sort()
    
    return [{"id": r[4], "rank": i+1} for i, r in enumerate(rows)]

def validate_and_migrate(bundle):
    # Reject oversized
    # In practice, limit to a reasonable size, e.g. 50MB (checked before parsing)
    
    v = bundle.get("schema_version")
    if not v:
        # V1 migration
        # v1 had {"metadata": {"strategies": [], "policy": ""}, "results": { strat_id: [...] }}
        bundle["schema_version"] = 2
        bundle["run_metadata"] = {
            "state": "imported_v1",
            "started_at": 0, "finished_at": 0, "elapsed": 0,
            "selected_strategy_count": len(bundle.get("metadata", {}).get("strategies", [])),
            "selected_target_count": 0, "planned_checks": 0, "completed_checks": 0
        }
        bundle["snapshots"] = {"strategies": [], "targets": []}
        bundle["upstream"] = {}
        bundle["policy"] = bundle.get("metadata", {}).get("policy", "")
        # v1 might not have aggregates
        bundle["aggregates"] = compute_aggregates(bundle.get("results", {}))
        ranks = compute_ranks(bundle["aggregates"])
        bundle["ranking_order"] = [r["id"] for r in ranks]
        bundle["best_strategy_id"] = ranks[0]["id"] if ranks else None
        return bundle, ["Migrated from v1"]
        
    if v == 2:
        warnings = []
        new_agg = compute_aggregates(bundle.get("results", {}))
        # simplistic check
        old_agg = bundle.get("aggregates", {}).get("strategies", {})
        for sid, n in new_agg["strategies"].items():
            o = old_agg.get(sid, {})
            if o.get("passed") != n["passed"] or abs(o.get("median_time", 0) - n["median_time"]) > 0.001:
                warnings.append(f"Aggregates mismatch for {sid}, recomputed.")
                break
        if warnings:
            bundle["aggregates"] = new_agg
            ranks = compute_ranks(new_agg)
            bundle["ranking_order"] = [r["id"] for r in ranks]
            bundle["best_strategy_id"] = ranks[0]["id"] if ranks else None
        return bundle, warnings
        
    raise ValueError(f"Unsupported schema version: {v}")

def export_csv_flat(bundle, filepath):
    # UTF-8 BOM
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=',')
        writer.writerow(["StrategyID", "TargetID", "Group", "Host", "Status", "Duration", "HTTP_Code", "ErrorMsg"])
        
        # Build targets lookup
        t_lookup = {t["target_id"]: t for t in bundle.get("snapshots", {}).get("targets", [])}
        
        for strat_id, targets_res in bundle.get("results", {}).items():
            for tr in targets_res:
                t_info = t_lookup.get(tr["target_id"], {})
                writer.writerow([
                    strat_id, tr["target_id"], t_info.get("group_name", "Unknown"),
                    t_info.get("host", tr["target_id"]), tr["status"], tr["duration"],
                    tr["http_code"], tr["error_msg"]
                ])

def export_csv_summary(bundle, filepath):
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=',')
        writer.writerow(["Rank", "StrategyID", "Passed", "Total", "SuccessRate%", "AvgTime", "MedianTime", "Errors"])
        
        rank_lookup = {r_id: i+1 for i, r_id in enumerate(bundle.get("ranking_order", []))}
        
        for strat_id, agg in bundle.get("aggregates", {}).get("strategies", {}).items():
            writer.writerow([
                rank_lookup.get(strat_id, 9999),
                strat_id,
                agg["passed"],
                agg["total"],
                f"{agg['success_rate']:.1f}",
                f"{agg['avg_time']:.2f}",
                f"{agg['median_time']:.2f}",
                agg["timeouts"] + agg["errors"]
            ])

def save_to_history(bundle, test_path=None):
    d = get_history_dir(test_path)
    # create new file
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filepath = os.path.join(d, f"run_{ts}.json")
    _atomic_write_json(filepath, bundle)
    
    # Prune max 20
    files = []
    for f in os.listdir(d):
        if f.endswith(".json") and f.startswith("run_"):
            files.append(os.path.join(d, f))
    files.sort(key=os.path.getmtime)
    
    while len(files) > 20:
        oldest = files.pop(0)
        try:
            os.remove(oldest)
        except:
            pass

def list_history(test_path=None):
    d = get_history_dir(test_path)
    records = []
    for f in os.listdir(d):
        if f.endswith(".json") and f.startswith("run_"):
            filepath = os.path.join(d, f)
            try:
                # To avoid loading huge files just for summary, we can parse partially or just load it
                with open(filepath, 'r', encoding='utf-8') as file_obj:
                    data = json.load(file_obj)
                    records.append({
                        "filepath": filepath,
                        "created_at": data.get("created_at", ""),
                        "state": data.get("run_metadata", {}).get("state", "unknown"),
                        "strategies": data.get("run_metadata", {}).get("selected_strategy_count", 0),
                        "targets": data.get("run_metadata", {}).get("selected_target_count", 0),
                        "best_strategy_id": data.get("best_strategy_id", ""),
                        "mtime": os.path.getmtime(filepath)
                    })
            except:
                pass
    records.sort(key=lambda x: x["mtime"], reverse=True)
    return records

def delete_history_record(filepath):
    if os.path.exists(filepath):
        os.remove(filepath)

def clear_history(test_path=None):
    d = get_history_dir(test_path)
    for f in os.listdir(d):
        if f.endswith(".json") and f.startswith("run_"):
            os.remove(os.path.join(d, f))

def compare_bundles(b1, b2):
    # Compare aggregates of b1 vs b2 (b2 is baseline usually, b1 is new)
    # Return table data for UI
    comp = []
    agg1 = b1.get("aggregates", {}).get("strategies", {})
    agg2 = b2.get("aggregates", {}).get("strategies", {})
    
    r1 = {s: i+1 for i, s in enumerate(b1.get("ranking_order", []))}
    r2 = {s: i+1 for i, s in enumerate(b2.get("ranking_order", []))}
    
    all_strats = set(agg1.keys()).union(set(agg2.keys()))
    
    for s in all_strats:
        a1 = agg1.get(s)
        a2 = agg2.get(s)
        
        passed1 = a1["passed"] if a1 else 0
        passed2 = a2["passed"] if a2 else 0
        d_passed = passed1 - passed2
        
        pct1 = a1["success_rate"] if a1 else 0
        pct2 = a2["success_rate"] if a2 else 0
        d_pct = pct1 - pct2
        
        med1 = a1["median_time"] if a1 else 0
        med2 = a2["median_time"] if a2 else 0
        d_med = med1 - med2
        
        rank1 = r1.get(s, 9999)
        rank2 = r2.get(s, 9999)
        d_rank = rank2 - rank1 # positive means improvement (smaller rank)
        if rank1 == 9999: d_rank = 0
        if rank2 == 9999: d_rank = 0
        
        comp.append({
            "id": s,
            "passed1": passed1,
            "passed2": passed2,
            "d_passed": d_passed,
            "pct1": pct1,
            "pct2": pct2,
            "d_pct": d_pct,
            "med1": med1,
            "med2": med2,
            "d_med": d_med,
            "rank1": rank1,
            "rank2": rank2,
            "d_rank": d_rank
        })
        
    comp.sort(key=lambda x: x["rank1"])
    return comp
