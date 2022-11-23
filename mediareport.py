import json
import sys
from typing import Dict, List, Optional
from sqlalchemy import Column, ForeignKey, Integer, String, DateTime
import sqlalchemy
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session, relationship
from mediascan import validate, Item, CONFIG_SCHEMA
import numpy as np
import re


episode_pattern = re.compile(r"S(\d+)E(\d+)", re.IGNORECASE)
episode_pattern_alt1 = re.compile(r"S(\d+)E(\d+)(-)(\d+)", re.IGNORECASE)
episode_pattern_alt2 = re.compile(r"S(\d+)((?:E\d+)+)", re.IGNORECASE)
season_pattern = re.compile(r"Season\ (\d+)", re.IGNORECASE)
show_pattern = re.compile(r"(/.+?)/Season\ \d+", re.IGNORECASE)
name_pattern = re.compile(r"^/.*/(.+)$", re.IGNORECASE)

sources = [ "bluray", "dvd", "webdl", "webrip", "stdtv", "hdtv"]


def sum_show(seasons: List[Item]) -> Dict:
    summary = {}
    summary["src"] = set()
    summary["res"] = set()
    summary["vcodecs"] = set()

    for season in seasons:
        summary["src"].update(season["src"])
        summary["res"].update(season["res"])
        summary["vcodecs"].update(season["vcodecs"])
        
    return summary

def extract_se(filename):
    # try spanning patterns (00-01)
    match = episode_pattern_alt1.search(filename)
    if match and match.group(3) == "-":
        s = match.group(1)
        first = match.group(2)
        last = match.group(4)
#        last = re.compile(r"S\d+E\d+-(\d+)").search(filename).group(4)
        return (int(s), [int(first), int(last)])

    # try multi-episode pattern (E01E02E03...)
    match = episode_pattern_alt2.search(filename)
    if match:
        s = match.group(1)
        all = match.group(2)
        if len(all) > 3:
            eplist = all[1:].split("E")
            return (int(s), [int(e) for e in eplist])

    # Lastly, try the typical pattern
    match = episode_pattern.search(filename)
    if match:
        s = match.group(1)
        ep = match.group(2)
        return (int(s), [int(ep)])

    return ()                        

def extract_src(filename: str) -> Optional[str]:
    copy = filename.lower()
    for source in sources:
        if source in copy:
            return source
    return "???"


if __name__ == "__main__":
    ##
    # load configuration and validate
    #
    with open("mediascan.json", "r") as f:
        config = json.load(f)

    try:
        validate(config, CONFIG_SCHEMA)
    except Exception as ex:
        print("There is a problem with the configuration file...")
        print(str(ex))
        sys.exit(1)

    for db in config["database"]:
        if db.get("enabled", True):
            db_url = db["connect"]
            break
    else:
        print("No enabled database configured")
        sys.exit(0)
        

    stats = {}        
    engine = create_engine(db_url, echo=False, future=True)
    with Session(engine) as session:
        
        results = session.query(Item.filepath, sqlalchemy.func.avg(Item.filesize_mb)).filter(Item.tag == "tv").group_by(Item.filepath).all()
        
        for path, _avg in results:
            #print(path)
                
            try:
                smatch = season_pattern.search(path)
                if smatch:
                    season = int(smatch.group(1))
                else:
                    season = 0

                if not season:
                    continue

                eplist = []
                sizes = []
                codecs = set()
                oop = []
                res = set()
                src = set()

                stats[path] = { "avg": int(_avg), "src": set(), "res": set(), "vcodecs": set() }
                
                #
                # process each episode
                #
                items = session.query(Item).filter(Item.filepath == path).all()
                if not items:
                    continue

                size = 0
                for item in items:

                    # filesizes
                    sizes.append(item.filesize_mb)
                    
                    # season and episode numbers
                    se = extract_se(item.filename)
                    if len(se) == 2:
                        s, e = se
                        if season > 0 and season != s:
                            oop.append(item.filename)
                        eplist.extend(e)
                    else:
                        print(f"Unable to parse season/episode(s) from {item.filename} -- skipped")
                        continue

                    codecs.add(item.vcodec)
                    res.add(item.height)
                    src.add(extract_src(item.filename))

                #
                # store details
                #
                stats[path]["season"] = season   
                stats[path]["std"] = int(np.std(sizes))
                stats[path]["max"] = np.max(sizes)
                stats[path]["min"] = np.min(sizes)

                mxe = np.max(eplist)
                egaps = set([e for e in range(1, mxe)]).difference(eplist)
                stats[path]["egaps"] = [str(gap) for gap in egaps]
                stats[path]["src"] = src
                stats[path]["res"] = res
                stats[path]["oop"] = oop
                stats[path]["vcodecs"] = codecs
                
            except Exception as ex:
                print(ex)
                print(f"** Unexpected error processing {path} -- skipping")            

        #
        # make a list of show titles
        #
        
        shows = set()
        for path in stats.keys():
            match = show_pattern.search(path)
            if match:
                shows.add(match.group(1))

        for show in sorted(shows):
            seasons = [v for k,v in stats.items() if k.startswith(show)]
            #print(show)
            summary = sum_show(seasons)

            name = name_pattern.match(show).group(1)
            print(f"{name}:")
            if len(summary["vcodecs"]) > 1:
                print(f"   Mixture of video codecs: {summary['vcodecs']}")
            #
            # Report on inconsistent source (br, webdl) at series level
            #
            if len(summary["src"]) > 1:
                print(f"   Mixture of video sources: {summary['src']}")
            #
            # Report on inconsistent resolutions
            #
            if len(summary["res"]) > 1:
                print(f"   Mixture of resolutions: {summary['res']}")

            for season in seasons:
                report = ""

                threshold = (season["std"] / season["min"]) * 100
                if season["std"] > season["min"] or threshold > 30.0:
                    report += f"     Inconsistent file sizes, possible quality issues (stddev={season['std']}, min={season['min']}, max={season['max']}), avg={season['avg']}\n"
                
                #
                # Report on out of place episodes
                #
                if "oop" in season and len(season["oop"]):
                    report += "     Out of place:\n"
                    for oop in season["oop"]:
                        report += f"       {oop}\n"
                                    
                #
                # Report on episode gaps
                #
                if "egaps" in season and len(season["egaps"]):
                    report += "      Missing: " + ",".join(season["egaps"]) + "\n"
                if "src" in season and len(season["src"]) > 1:
                    report += f"     Sources: {season['src']}\n"
                if len(season["vcodecs"]) > 1:
                    report += f"     Video codecs: {season['vcodecs']}\n"
                if len(season["res"]) > 1:
                    report += f"     Resolutions: {season['res']}\n"

                if len(report) > 0:
                    report = f"   Season {season['season']}\n" + report
                    print(report)

      