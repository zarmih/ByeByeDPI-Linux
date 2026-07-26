#!/usr/bin/env python3
import argparse
import json
import logging
import sys
import urllib.request
import urllib.error
from pathlib import Path
import os
from typing import List, Dict, Any, Optional
import time

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

UPSTREAM_REPO = "romanvht/ByeByeDPI"
UPSTREAM_COMMIT = "ffda4fa93d94472217c75e51b45fdd18f966c0af"
ASSETS_URL_BASE = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{UPSTREAM_COMMIT}/app/src/main/assets"
TARGET_FILES = [
    "proxytest_cloudflare.sites",
    "proxytest_discord.sites",
    "proxytest_general.sites",
    "proxytest_googlevideo.sites",
    "proxytest_social.sites",
    "proxytest_telegram.sites",
    "proxytest_türkiye.sites",
    "proxytest_youtube.sites",
]

DEFAULT_ACTIVE_GROUPS = ["youtube", "googlevideo"]

def fetch_file(url: str, proxy: Optional[str] = None) -> Optional[str]:
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url)
    try:
        with opener.open(req, timeout=30) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        logging.error(f"Failed to fetch {url}: {e}")
        return None

def fetch_local(path: str) -> Optional[str]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logging.error(f"Failed to read {path}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Update test targets from ByeByeDPI Android repository")
    parser.add_argument("--dry-run", action="store_true", help="Do not save, just print results")
    parser.add_argument("--local-dir", type=str, help="Path to local romanvht-ByeByeDPI directory to read from instead of downloading")
    parser.add_argument("--proxy", type=str, help="HTTP(s) proxy URL, e.g. http://127.0.0.1:10808")
    parser.add_argument("--output", type=str, default="data/test_targets.json", help="Output JSON file")
    args = parser.parse_args()

    groups = []
    total_targets = 0

    for filename in TARGET_FILES:
        group_id = filename.replace("proxytest_", "").replace(".sites", "")
        group_name = group_id.capitalize()
        enabled_by_default = group_id in DEFAULT_ACTIVE_GROUPS

        if args.local_dir:
            file_path = os.path.join(args.local_dir, "app/src/main/assets", filename)
            content = fetch_local(file_path)
            source_url = f"file://{file_path}"
        else:
            url = f"{ASSETS_URL_BASE}/{filename}"
            content = fetch_file(url, args.proxy)
            source_url = url
            time.sleep(0.5) # rate limit

        if content is None:
            logging.error("Aborting update due to fetch errors.")
            sys.exit(1)

        domains = [line.strip() for line in content.splitlines() if line.strip()]
        
        targets = []
        for idx, domain in enumerate(domains):
            targets.append({
                "target_id": f"{group_id}_{idx}",
                "label": domain,
                "host": domain,
                "url": f"https://{domain}/", # Convert domains to https URLs for tests
                "test_type": "http_head",
                "notes": ""
            })
            total_targets += 1
            
        groups.append({
            "group_id": group_id,
            "group_name": group_name,
            "enabled_by_default": enabled_by_default,
            "source": source_url,
            "upstream_commit": UPSTREAM_COMMIT,
            "targets": targets
        })

    logging.info(f"Successfully processed {len(groups)} groups containing {total_targets} targets.")
    
    data = {
        "metadata": {
            "upstream_repo": UPSTREAM_REPO,
            "upstream_commit": UPSTREAM_COMMIT,
            "total_groups": len(groups),
            "total_targets": total_targets,
            "format_version": 1
        },
        "groups": groups
    }

    if args.dry_run:
        logging.info("Dry run complete. No files written.")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
        
    logging.info(f"Saved to {args.output}")

if __name__ == '__main__':
    main()
