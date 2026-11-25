"""Refresh the published week's race entries from NAR. No historical results changed."""
import datetime as dt
import json
import pathlib
import re
import time
import unicodedata
import urllib.parse
import requests
from bs4 import BeautifulSoup

FILE = pathlib.Path("week_cards.json")
BASE = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable"
JST = dt.timezone(dt.timedelta(hours=9))
session = requests.Session()
session.headers["User-Agent"] = "KochiRaceLevelResearch/0.9 (public race-card analysis)"

def text(node):
    return unicodedata.normalize("NFKC", node.get_text(" ", strip=True)).strip()

def parse(html, expected):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.select("a[href]"):
        href = a.get("href", "").lower()
        if "horsemarkinfo" not in href and "k_lineagelogincode" not in href:
            continue
        td = a.find_parent("td")
        tr = a.find_parent("tr")
        if td is None or tr is None:
            continue
        cells = tr.find_all("td", recursive=False)
        if td not in cells:
            continue
        i = cells.index(td)
        if i == 0:
            continue
        raw = text(cells[i - 1])
        if not re.fullmatch(r"\d{1,2}", raw):
            continue
        n = int(raw)
        name = text(a)
        if not (1 <= n <= expected) or not name:
            continue
        # Only inspect the current horse's entry cells; past race results can
        # contain unrelated scratch notices.
        entry = " ".join(text(x) for x in cells[i:i + 3])
        withdrawn = bool(re.search(r"出走取消|競走除外", entry))
        row = {"n": n, "name": name}
        if withdrawn:
            row["withdrawn"] = True
        if n in found and found[n]["name"] != name:
            raise ValueError(f"Conflicting horse number: {n}")
        found[n] = row
    if set(found) != set(range(1, expected + 1)):
        raise ValueError(f"Expected {expected} entries, parsed {len(found)}")
    return [found[n] for n in sorted(found)]

def fetch(card):
    date = card["date"]
    params = {"k_babaCode":31, "k_raceDate":date.replace("-", "/"), "k_raceNo":card["r"]}
    resp = session.get(BASE, params=params, timeout=(10,25))
    resp.raise_for_status()
    if "keiba.go.jp" not in urllib.parse.urlparse(resp.url).hostname:
        raise ValueError("Unexpected source")
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    return parse(resp.text, card["count"])

def main():
    data = json.loads(FILE.read_text(encoding="utf-8"))
    updated = 0
    failed = []
    for c in data["races"]:
        try:
            horses = fetch(c)
            c["horses"] = horses
            c["source"] = c["url"]
            updated += 1
            print(c["date"], c["r"], "OK", len(horses))
        except (requests.RequestException, ValueError) as exc:
            failed.append({"date":c["date"], "r":c["r"], "error":str(exc)[:160]})
            print(c["date"], c["r"], "FAILED", str(exc)[:160])
        time.sleep(1.2)
    if updated:
        data["asOf"] = dt.datetime.now(JST).date().isoformat()
    data["lastAttempt"] = dt.datetime.now(JST).isoformat(timespec="seconds")
    data["fetchErrors"] = failed
    temp = FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    temp.replace(FILE)
    print(f"Updated {updated}/{len(data['races'])} races; retained verified prior cards.")

if __name__ == "__main__":
    main()
