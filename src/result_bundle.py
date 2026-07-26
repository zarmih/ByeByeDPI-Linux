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
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
MAX_STRATEGIES = 1000
MAX_TARGETS = 10000
MAX_RESULTS = 100000
MAX_STRING_LENGTH = 16384
ALLOWED_STATES = {"completed", "cancelled", "partial", "imported", "imported_v1", "paused"}
ALLOWED_RESULT_STATUSES = {"Success", "Failed", "Fail", "Timeout", "Error"}

def get_history_dir(test_path=None):
    if test_path:
        d = test_path
    else:
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        d = os.path.join(app_data, "ByeByeDPI-Linux", "history")
    os.makedirs(d, exist_ok=True)
    return d

def _atomic_write_json(filepath, data):
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, filepath)

def save_bundle(filepath, bundle):
    """Atomically write a sanitized result bundle."""
    _atomic_write_json(str(filepath), _remove_secrets(bundle))

def _remove_secrets(data):
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            kl = k.lower()
            if any(x in kl for x in ["token", "password", "secret", "api_key", "cookie", "authorization"]):
                new_dict[k] = "***REDACTED***"
            else:
                new_dict[k] = _remove_secrets(v)
        return new_dict
    elif isinstance(data, list):
        return [_remove_secrets(i) for i in data]
    elif isinstance(data, str):
        if "http://" not in data and "https://" not in data:
            if "/mnt/" in data or "/home/" in data or "file://" in data:
                return "***REDACTED_PATH***"
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
    aggregates = compute_aggregates(results_matrix, targets_snapshots)
    ranks = compute_ranks(aggregates)
    best_id = ranks[0]["id"] if ranks else None

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "app": {"name": "ByeByeDPI-Linux", "version": APP_VERSION},
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_metadata": {
            "started_at": started_at,
            "finished_at": finished_at,
            "state": state,
            "elapsed": (finished_at - started_at) if started_at and finished_at else 0,
            "selected_strategy_count": selected_strategy_count,
            "selected_target_count": selected_target_count,
            "planned_checks": planned_checks,
            "completed_checks": completed_checks,
            "cancelled": state == "cancelled",
            "paused": state == "paused"
        },
        "upstream": _remove_secrets(upstream_info),
        "policy": _remove_secrets(policy_info),
        "snapshots": {
            "strategies": _remove_secrets(strategies_snapshots),
            "targets": _remove_secrets(targets_snapshots)
        },
        "results": _remove_secrets(results_matrix),
        "aggregates": aggregates,
        "ranking_order": [r["id"] for r in ranks],
        "best_strategy_id": best_id,
        "diagnostics": [],
        "warnings": []
    }
    return bundle

def compute_aggregates(results_matrix, targets_snapshots=None):
    aggregates = {"strategies": {}, "groups": {}}
    t_group = {}
    if targets_snapshots:
        for t in targets_snapshots:
            t_group[t["target_id"]] = t.get("group_name", "Unknown")

    for strat_id, res_list in results_matrix.items():
        passed = sum(1 for r in res_list if r["status"] == "Success")
        total = len(res_list)
        timeout = sum(1 for r in res_list if r["status"] == "Timeout")
        errors = sum(1 for r in res_list if r["status"] == "Error")
        succ_durs = [r["duration"] for r in res_list if r["status"] == "Success"]

        avg = statistics.mean(succ_durs) if succ_durs else 0.0
        med = statistics.median(succ_durs) if succ_durs else 0.0

        aggregates["strategies"][strat_id] = {
            "passed": passed,
            "total": total,
            "success_rate": (passed / total * 100) if total > 0 else 0,
            "avg_time": avg,
            "median_time": med,
            "timeouts": timeout,
            "errors": errors
        }

        if targets_snapshots:
            if strat_id not in aggregates["groups"]:
                aggregates["groups"][strat_id] = {}

            for r in res_list:
                grp = t_group.get(r["target_id"], "Unknown")
                if grp not in aggregates["groups"][strat_id]:
                    aggregates["groups"][strat_id][grp] = {"passed": 0, "total": 0}
                aggregates["groups"][strat_id][grp]["total"] += 1
                if r["status"] == "Success":
                    aggregates["groups"][strat_id][grp]["passed"] += 1

    return aggregates

def compute_ranks(aggregates):
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

def load_bundle(filepath):
    if os.path.getsize(filepath) > MAX_FILE_SIZE_BYTES:
        raise ValueError("File is too large (>50MB).")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Invalid bundle format: top-level must be a dictionary.")
    return validate_and_migrate(data)

def validate_and_migrate(bundle):
    if not isinstance(bundle, dict):
        raise ValueError("Bundle must be a dictionary.")
    v = bundle.get("schema_version")

    if not v:
        bundle["schema_version"] = 2
        bundle["app"] = {"name": "ByeByeDPI-Linux", "version": APP_VERSION}
        bundle["run_metadata"] = {
            "state": "imported_v1",
            "started_at": 0, "finished_at": 0, "elapsed": 0,
            "selected_strategy_count": len(bundle.get("metadata", {}).get("strategies", [])),
            "selected_target_count": 0, "planned_checks": 0, "completed_checks": 0
        }
        bundle["snapshots"] = {"strategies": [], "targets": []}
        bundle["upstream"] = {}
        bundle["policy"] = bundle.get("metadata", {}).get("policy", "")
        bundle["diagnostics"] = []
        bundle["warnings"] = []

    elif v != 2:
        raise ValueError(f"Unsupported schema version: {v}")

    bundle.setdefault("app", {"name": "ByeByeDPI-Linux", "version": APP_VERSION})
    bundle.setdefault("upstream", {})
    bundle.setdefault("policy", {})
    bundle.setdefault("diagnostics", [])
    bundle.setdefault("warnings", [])
    bundle.setdefault("snapshots", {"strategies": [], "targets": []})
    bundle.setdefault("results", {})

    if not isinstance(bundle.get("run_metadata"), dict):
        raise ValueError("Invalid run_metadata type.")
    if not isinstance(bundle.get("snapshots"), dict):
        raise ValueError("Invalid snapshots type.")
    if not isinstance(bundle.get("results"), dict):
        raise ValueError("Invalid results type.")

    run_metadata = bundle["run_metadata"]
    run_metadata.setdefault("cancelled", run_metadata.get("state") == "cancelled")
    run_metadata.setdefault("paused", run_metadata.get("state") == "paused")

    state = bundle.get("run_metadata", {}).get("state", "")
    if state not in ALLOWED_STATES:
        raise ValueError(f"Invalid state: {state}")

    strats = bundle.get("snapshots", {}).get("strategies", [])
    targs = bundle.get("snapshots", {}).get("targets", [])
    if not isinstance(strats, list) or not isinstance(targs, list):
        raise ValueError("Snapshots strategies and targets must be lists.")
    if len(strats) > MAX_STRATEGIES:
        raise ValueError("Too many strategies.")
    if len(targs) > MAX_TARGETS:
        raise ValueError("Too many targets.")

    for t in targs:
        url = t.get("url", "")
        if url and not url.startswith("http://") and not url.startswith("https://"):
            raise ValueError(f"Invalid URL snapshot: {url}")

    res = bundle.get("results", {})
    total_res = 0
    for strategy_id, rows in res.items():
        if not isinstance(strategy_id, str) or not isinstance(rows, list):
            raise ValueError("Invalid results matrix type.")
        total_res += len(rows)
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid result row type.")
            status = row.get("status")
            if status is not None and status not in ALLOWED_RESULT_STATUSES:
                raise ValueError(f"Invalid result status: {status}")
            for value in row.values():
                if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
                    raise ValueError("Result string is too long.")
    if total_res > MAX_RESULTS:
        raise ValueError("Too many result rows.")

    warnings = bundle.get("warnings", [])
    if not v:
        warnings.append("Migrated from v1")

    new_agg = compute_aggregates(res, targs)
    old_agg = bundle.get("aggregates", {}).get("strategies", {})

    mismatch = False
    for sid, n in new_agg["strategies"].items():
        o = old_agg.get(sid, {})
        if o.get("passed") != n["passed"] or abs(o.get("median_time", 0) - n["median_time"]) > 0.001:
            mismatch = True
            break

    if mismatch:
        warnings.append("Aggregates mismatch found. Recomputed.")

    bundle["aggregates"] = new_agg
    ranks = compute_ranks(new_agg)
    new_ranking = [r["id"] for r in ranks]

    new_best_id = ranks[0]["id"] if ranks else None

    if bundle.get("ranking_order") != new_ranking or bundle.get("best_strategy_id") != new_best_id:
        if "Ranking mismatch found. Recomputed." not in warnings:
            warnings.append("Ranking mismatch found. Recomputed.")

    bundle["ranking_order"] = new_ranking
    bundle["best_strategy_id"] = new_best_id
    bundle["warnings"] = warnings

    # Backwards compatibility check
    if "app_version" in bundle:
        bundle["app"] = {"name": "ByeByeDPI-Linux", "version": bundle["app_version"]}

    bundle = _remove_secrets(bundle)
    bundle["warnings"] = warnings
    return bundle, warnings

def export_csv_flat(bundle, filepath):
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(["StrategyID", "TargetID", "Group", "Host", "Status", "Duration", "HTTP_Code", "ErrorMsg"])

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
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(["Rank", "StrategyID", "Passed", "Total", "SuccessRate%", "AvgTime", "MedianTime", "Errors"])

        rank_lookup = {r_id: i+1 for i, r_id in enumerate(bundle.get("ranking_order", []))}
        for strat_id, agg in bundle.get("aggregates", {}).get("strategies", {}).items():
            writer.writerow([
                rank_lookup.get(strat_id, 9999), strat_id, agg["passed"], agg["total"],
                f"{agg['success_rate']:.1f}", f"{agg['avg_time']:.2f}",
                f"{agg['median_time']:.2f}", agg["timeouts"] + agg["errors"]
            ])

def save_to_history(bundle, test_path=None):
    d = get_history_dir(test_path)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filepath = os.path.join(d, f"run_{ts}.json")
    save_bundle(filepath, bundle)

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
                bundle, _ = load_bundle(filepath)
                records.append({
                    "filepath": filepath,
                    "created_at": bundle.get("created_at", ""),
                    "state": bundle.get("run_metadata", {}).get("state", "unknown"),
                    "strategies": bundle.get("run_metadata", {}).get("selected_strategy_count", 0),
                    "targets": bundle.get("run_metadata", {}).get("selected_target_count", 0),
                    "best_strategy_id": bundle.get("best_strategy_id", ""),
                    "mtime": os.path.getmtime(filepath)
                })
            except:
                pass
    records.sort(key=lambda x: x["mtime"], reverse=True)
    return records

def delete_history_record(filepath, test_path=None):
    d = os.path.abspath(get_history_dir(test_path))
    fp = os.path.abspath(filepath)
    if os.path.commonpath([d, fp]) != d:
        raise ValueError("Path traversal attempt.")
    if os.path.exists(fp):
        os.remove(fp)

def clear_history(test_path=None):
    d = get_history_dir(test_path)
    for f in os.listdir(d):
        if f.endswith(".json") and f.startswith("run_"):
            os.remove(os.path.join(d, f))

def compare_bundles(b1, b2):
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
        d_rank = rank2 - rank1
        if rank1 == 9999: d_rank = 0
        if rank2 == 9999: d_rank = 0
        comp.append({
            "id": s, "passed1": passed1, "passed2": passed2, "d_passed": d_passed,
            "pct1": pct1, "pct2": pct2, "d_pct": d_pct, "med1": med1, "med2": med2,
            "d_med": d_med, "rank1": rank1, "rank2": rank2, "d_rank": d_rank
        })
    comp.sort(key=lambda x: x["rank1"])
    return comp
