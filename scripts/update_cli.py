from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from update_manager import UpdateError, UpdateManager


def run_update_cli(kind: str) -> int:
    default_name = "strategies.json" if kind == "strategies" else "test_targets.json"
    parser = argparse.ArgumentParser(
        description=f"Safely preview and update ByeByeDPI {kind}"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview and validate without writing")
    parser.add_argument("--local-dir", help="Local romanvht/ByeByeDPI checkout used instead of network")
    parser.add_argument("--proxy", help="Optional HTTP proxy, e.g. http://127.0.0.1:10808")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / default_name),
        help="Destination JSON path",
    )
    parser.add_argument("--rollback", action="store_true", help="Restore the newest validated backup")
    parser.add_argument("--print-json", action="store_true", help="Print the full validated candidate")
    args = parser.parse_args()

    active_data_dir = PROJECT_ROOT / "data"
    manager = UpdateManager(active_data_dir)
    try:
        if args.rollback:
            restored = manager.rollback(kind)
            print(f"Restored {kind} from {restored}")
            return 0

        if args.local_dir:
            preview = manager.preview_local(kind, args.local_dir)
        else:
            preview = manager.preview_remote(kind, args.proxy)
        print(preview.report())
        if args.print_json:
            print(json.dumps(preview.candidate, ensure_ascii=False, indent=2))
        if args.dry_run:
            print("Dry run complete. No files were changed.")
            return 0

        output = Path(args.output).resolve()
        active_path = (active_data_dir / default_name).resolve()
        if output == active_path:
            backup = manager.apply(preview)
            print(f"Applied validated {kind} update. Backup: {backup}")
        else:
            written = manager.export_candidate(preview, output)
            print(f"Exported validated candidate to {written}")
        return 0
    except UpdateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
