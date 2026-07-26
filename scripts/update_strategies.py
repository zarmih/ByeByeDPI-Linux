#!/usr/bin/env python3
import json
import urllib.request
import re

URL = "https://raw.githubusercontent.com/romanvht/ByeByeDPI/master/app/src/main/assets/proxytest_strategies.list"
COMMIT_URL = "https://api.github.com/repos/romanvht/ByeByeDPI/commits/master"

def get_latest_commit():
    try:
        req = urllib.request.Request(COMMIT_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get('sha', 'unknown')
    except Exception as e:
        print(f"Error fetching commit: {e}")
        return "unknown"

def main():
    print(f"Fetching latest strategies from {URL} ...")
    try:
        req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            content = response.read().decode('utf-8')
    except Exception as e:
        print(f"Failed to fetch strategies: {e}")
        return

    commit = get_latest_commit()
    
    strategies = []
    lines = [line.strip() for line in content.splitlines()]
    for i, line in enumerate(lines):
        if not line or line.startswith('#'):
            continue
        
        strategies.append({
            "id": f"strategy_{len(strategies)+1}",
            "name": f"Strategy {len(strategies)+1}",
            "args": line,
            "source": "romanvht/ByeByeDPI (app/src/main/assets/proxytest_strategies.list)",
            "upstream_commit": commit,
            "enabled": True,
            "supported": True,
            "notes": "Placeholder {sni} is typically replaced with the target domain or www.google.com during testing." if "{sni}" in line else ""
        })

    if not strategies:
        print("Error: No strategies parsed. Data will not be overwritten.")
        return

    out_file = 'data/strategies.json'
    import sys
    if '--dry-run' in sys.argv:
        print("Dry-run mode, skipping save.")
    else:
        with open(out_file, 'w') as f:
            json.dump({"strategies": strategies}, f, indent=4)
        print(f"Successfully updated {out_file}.")
    
    print(f"Total strategies: {len(strategies)}")
    print(f"Upstream commit: {commit}")

if __name__ == '__main__':
    main()
