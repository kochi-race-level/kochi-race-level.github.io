"""Settle frozen predictions from NAR's official result/payout tables.
Fail closed on incomplete or ambiguous result pages; never infer payouts from odds.
"""
import datetime as dt
import json
import pathlib
import re
import time
import unicodedata
import requests
from bs4 import BeautifulSoup

FILE = pathlib.Path("prediction_history.json")
BASE = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable"
JST = dt.timezone(dt.timedelta(hours=9))
session = requests.Session()
session.headers["User-Agent"] = "KochiRaceLevelResearch/1.0 (official result verification)"

def compact(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s)))

def txt(node):
    return compact(node.get_text(" ", strip=True))

def table_rows(table):
    return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]

def grid(table):
    """Expand rowspan/colspan to cell references, preserving logical columns."""
    active = {}
    for tr in table_rows(table):
        row = {i: cell for i, (cell, remaining) in active.items()}
        active = {i: (cell, rem-1) for i,(cell,rem) in active.items() if rem>1}
        pos = 0
        for cell in tr.find_all(["td","th"], recursive=False):
            while pos in row:
                pos += 1
            width = int(cell.get("colspan",1))
            height = int(cell.get("rowspan",1))
            for i in range(pos,pos+width):
                if i in row:
                    raise ValueError("Overlapping table cells")
                row[i] = cell
                if height>1:
                    active[i] = (cell,height-1)
            pos += width
        if row:
            yield [row.get(i) for i in range(max(row)+1)]

def unique_cells(row):
    out=[]
    for cell in row:
        if cell is not None and (not out or out[-1] is not cell):
            out.append(cell)
    return out

def parse(html, race):
    soup=BeautifulSoup(html,"html.parser")
    # Verify the date/venue/race heading, not a link to another race.
    d=dt.date.fromisoformat(race["date"])
    heading=f"{d.year}年{d.month}月{d.day}日"
    page=txt(soup)
    if not re.search(re.escape(heading)+r".{0,30}高知第"+str(race["r"])+r"競走",page):
        raise ValueError("Date/venue/race heading not verified")
    results={}
    result_table=None
    for table in soup.find_all("table"):
        cols=None
        candidate={}
        for row in grid(table):
            cells=unique_cells(row)
            t=[txt(c) for c in cells]
            if all(k in t for k in ("着順","馬番","馬名","人気")):
                cols={k:t.index(k) for k in ("着順","馬番","馬名","人気")}
                continue
            if cols is None or len(t)<=max(cols.values()):
                continue
            n=t[cols["馬番"]]; rank=t[cols["着順"]]; name=t[cols["馬名"]]; pop=t[cols["人気"]]
            if not re.fullmatch(r"\d{1,2}",n) or not name:
                continue
            n=int(n)
            if rank in ("取消","出走取消","除外","競走除外"):
                item={"name":name,"status":"cancelled","finish":None,"popularity":None}
            elif re.fullmatch(r"\d{1,2}",rank) or rank in ("中止","競走中止","失格"):
                if not re.fullmatch(r"\d{1,2}",pop) or int(pop)<1:
                    raise ValueError("Missing final popularity")
                item={"name":name,"status":"ran","finish":int(rank) if rank.isdigit() else rank,"popularity":int(pop)}
                if isinstance(item["finish"],int) and item["finish"]<1:
                    raise ValueError("Invalid finishing position")
            else:
                raise ValueError("Unknown finish: "+rank)
            if n in candidate:
                raise ValueError("Duplicate result horse")
            candidate[n]=item
        if candidate:
            if result_table is not None:
                raise ValueError("Multiple result tables")
            results=candidate
            result_table=table
    if not results or len(results)!=race["entryCount"]:
        raise ValueError("Incomplete result rows")
    for p in race["picks"]:
        if p["n"] not in results or compact(p["name"])!=results[p["n"]]["name"]:
            raise ValueError("Prediction horse number/name mismatch")
    ran=[(n,h) for n,h in results.items() if h["status"]=="ran"]
    if len(ran)<5:
        raise ValueError("Special small-field or cancelled race; manual review")
    finishers=[(n,h["finish"]) for n,h in ran if isinstance(h["finish"],int)]
    winners={n for n,k in finishers if k==1}
    # Place payout depends on the number of starters; if it differs from the
    # published payouts (e.g. pre-sale scratches), do not settle automatically.
    places={n for n,k in finishers if k<=(3 if len(ran)>=8 else 2)}
    payouts={"単勝":{},"複勝":{}}
    for table in soup.find_all("table"):
        if table is result_table:
            continue
        for row in grid(table):
            cells=unique_cells(row)
            t=[txt(c) for c in cells]
            for i,k in enumerate(t):
                if k not in payouts or i+2>=len(t):
                    continue
                n,amount=t[i+1:i+3]
                if not re.fullmatch(r"\d{1,2}",n) or not re.fullmatch(r"[\d,]+円",amount):
                    continue
                n=int(n); amount=int(amount.replace(",","").replace("円",""))
                if amount<100 or amount%10:
                    raise ValueError("Invalid or special payout")
                if n in payouts[k] and payouts[k][n]!=amount:
                    raise ValueError("Conflicting payout")
                payouts[k][n]=amount
    if not winners or not places or set(payouts["単勝"])!=winners or set(payouts["複勝"])!=places:
        raise ValueError("Incomplete/special payout table; manual review")
    settled=[]
    for p in race["picks"]:
        n=p["n"]; h=results[n]
        settled.append({"rank":p["rank"],"n":n,"name":p["name"],"status":h["status"],"finish":h["finish"],"popularity":h["popularity"],"win":payouts["単勝"].get(n,0),"place":payouts["複勝"].get(n,0)})
    return settled

def self_test():
    race={"date":"2026-11-22","r":11,"entryCount":8,"picks":[{"rank":1,"n":3,"name":"エリジブル"},{"rank":2,"n":1,"name":"ベンガルボダイジュ"}]}
    # Synthetic HTML exercising the published result/payout format, not a live-page test.
    horses=[(3,"エリジブル",1,10),(1,"ベンガルボダイジュ",2,1),(9,"シデレウス",3,11),(2,"テストA",4,2),(4,"テストB",5,3),(5,"テストC",6,4),(6,"テストD",7,5),(7,"テストE",8,6)]
    body="<h2>2026年11月22日（日） 高 知 第11競走 競走成績</h2><table><tr><th>着順</th><th>枠</th><th>馬番</th><th>馬名</th><th>人気</th></tr>"
    for n,name,fin,pop in horses:
        body+=f"<tr><td>{fin}</td><td>1</td><td>{n}</td><td>{name}</td><td>{pop}</td></tr>"
    body+="</table><table><tr><th>単勝</th><td>3</td><td>2,150円</td></tr><tr><th rowspan='3'>複勝</th><td>3</td><td>390円</td></tr><tr><td>1</td><td>210円</td></tr><tr><td>9</td><td>650円</td></tr></table>"
    result=parse(body,race)
    assert [(x["finish"],x["win"],x["place"]) for x in result]==[(1,2150,390),(2,0,210)]
    try:
        parse(body.replace("650円",""),race)
    except ValueError:
        pass
    else:
        raise AssertionError("Missing payout must fail closed")
    print("Synthetic settlement tests passed")

def main():
    self_test()
    data=json.loads(FILE.read_text(encoding="utf-8"))
    now=dt.datetime.now(JST)
    count=0
    for race in data["races"]:
        if race["result"] is not None or not race["picks"]:
            continue
        # Check only after the scheduled race, allow time for official payouts.
        if now < dt.datetime.fromisoformat(race["scheduled"])+dt.timedelta(minutes=90):
            continue
        try:
            resp=session.get(BASE,params={"k_babaCode":31,"k_raceDate":race["date"].replace("-","/"),"k_raceNo":race["r"]},timeout=(10,30))
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower()=="iso-8859-1":
                resp.encoding=resp.apparent_encoding
            settled=parse(resp.text,race)
            race["result"]={"confirmedAt":now.isoformat(timespec="seconds"),"source":resp.url,"horses":settled}
            count+=1
            print("Settled",race["date"],race["r"])
        except (requests.RequestException,ValueError) as exc:
            print("Pending",race["date"],race["r"],str(exc)[:180])
        time.sleep(1.2)
    if count:
        temp=FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        temp.replace(FILE)
    print("New settlements:",count)

if __name__=="__main__":
    main()
