#!/usr/bin/env python3
"""Download the e-Gov 法令検索 bulk XML archive and the law list metadata (API v2).

Raw data is cached under RAW_DIR (default: ../../_raw/jp relative to this script) so re-runs
do not re-download unless --force is given.

Usage: python scripts/fetch.py [--raw DIR] [--force]
"""
import argparse
import json
import os
import sys
import time
import zipfile

import requests

UA = "LawCodex/1.0 (+https://github.com/LawCodex)"
BULK_URL = "https://laws.e-gov.go.jp/bulkdownload?file_section=1&only_xml_flag=true"
API_LIST = "https://laws.e-gov.go.jp/api/2/laws"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RAW = os.path.normpath(os.path.join(HERE, "..", "..", "_raw", "jp"))


def get(session, url, **kw):
    for attempt in range(6):
        try:
            r = session.get(url, timeout=600, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
        except (requests.RequestException, OSError) as e:
            wait = 2 ** attempt * 5
            print(f"  retry {attempt + 1} for {url}: {e} (sleep {wait}s)", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed: {url}")


def fetch_bulk(session, raw, force):
    zpath = os.path.join(raw, "all_xml.zip")
    if os.path.exists(zpath) and not force:
        try:
            with zipfile.ZipFile(zpath) as z:
                z.namelist()
            print(f"cached: {zpath}")
            return zpath
        except zipfile.BadZipFile:
            pass
    # The server does not support Range requests and sometimes truncates the
    # transfer, so retry the whole download until the archive validates.
    tmp = zpath + ".part"
    for attempt in range(5):
        print(f"downloading {BULK_URL} (attempt {attempt + 1})")
        try:
            with get(session, BULK_URL, stream=True) as r, open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            with zipfile.ZipFile(tmp) as z:
                if z.testzip() is None:
                    os.replace(tmp, zpath)
                    return zpath
        except (requests.RequestException, zipfile.BadZipFile, OSError) as e:
            print(f"  download failed: {e}", file=sys.stderr)
        time.sleep(30 * (attempt + 1))
    raise RuntimeError("bulk download failed")


def fetch_list(session, raw, force):
    out = os.path.join(raw, "laws_list.json")
    if os.path.exists(out) and not force:
        print(f"cached: {out}")
        return out
    laws, offset, limit = [], 0, 1000
    while True:
        r = get(session, API_LIST, params={"limit": limit, "offset": offset,
                                           "response_format": "json"})
        d = r.json()
        laws.extend(d["laws"])
        print(f"  list: {len(laws)}/{d['total_count']}")
        if not d.get("next_offset") or len(laws) >= d["total_count"]:
            break
        offset = d["next_offset"]
        time.sleep(1)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(laws, f, ensure_ascii=False)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=DEFAULT_RAW)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.raw, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    fetch_list(s, a.raw, a.force)
    if not a.list_only:
        zpath = fetch_bulk(s, a.raw, a.force)
        xdir = os.path.join(a.raw, "xml")
        if a.force or not os.path.isdir(xdir):
            print(f"extracting to {xdir}")
            with zipfile.ZipFile(zpath) as z:
                z.extractall(xdir)


if __name__ == "__main__":
    main()
