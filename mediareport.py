import json
import os
import sys
from typing import Dict, List, Optional
from sqlalchemy import Column, ForeignKey, Integer, String, DateTime
import sqlalchemy
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session, relationship, joinedload
from mediascan import validate, Item, Audio
import numpy as np
import re
import yaml


episode_pattern = re.compile(r"S(\d+)E(\d+)", re.IGNORECASE)
episode_pattern_alt1 = re.compile(r"S(\d+)E(\d+)(-)(\d+)", re.IGNORECASE)
episode_pattern_alt2 = re.compile(r"S(\d+)((?:E\d+)+)", re.IGNORECASE)
season_pattern = re.compile(r"Season\ (\d+)", re.IGNORECASE)
show_pattern = re.compile(r"(/.+?)/Season\ \d+", re.IGNORECASE)
name_pattern = re.compile(r"^/.*/(.+)$", re.IGNORECASE)
trunc_pattern = re.compile(r"^.*(S\d+E\d+.*)", re.IGNORECASE)

sources = [ "bluray", "dvd", "webdl", "webrip", "sdtv", "hdtv"]


def sum_show(seasons: List[Item]) -> Dict:
    summary = {}
    summary["src"] = set()
    summary["res"] = set()
    summary["vcodecs"] = set()
    summary["pixformats"] = set()

    for season in seasons:
        summary["src"].update(season["src"])
        summary["res"].update(season["res"])
        summary["vcodecs"].update(season["vcodecs"])
        summary["pixformats"].update(season["pixformats"])
        
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

def mixed_sources(sources):                
    if "bluray" in sources and len(sources) > 1:
        return True
    if "dvd" in sources and len(sources) > 1:
        return True
    return False

def details_header() -> str:
    return f"   {'Episode':65} {'Dur':>7} {'Size(mb)':>8} {'FPS':>5} {'Resolution'} {'Color':>10} {'Pixel Fmt':>12}"

def details(item: Item) -> str:
    match = trunc_pattern.search(item.filename)
    if match:
        partial = match.group(1)
    else:
        partial = item.filename
    details = f"   {partial:65} {item.duration:>7} {item.filesize_mb:>8} {item.fps:>5} {item.width:>5}x{item.height:<4} {item.color_space or '':>10} {item.pix_format:>12}"
    return details

#
# main
#

if __name__ == "__main__":

    report_codecs = False
    show_details = False
    
    if len(sys.argv) > 1:
        for arg in sys.argv:
            if arg == "-c":
                report_codecs = True
            elif arg == "-d":
                show_details = True

    ##
    # load configuration and validate
    #
    with open("mediascan.yml", "r") as f:
        config = yaml.load(f, Loader=yaml.Loader)

    for db in config["database"]:
        if db.get("enabled", True):
            db_url = db["connect"]
            break
    else:
        print("No enabled database configured")
        sys.exit(0)
        
    if os.path.exists("mediaopts.json"):
        with open("mediaopts.json", "r") as mediafile:
            media_options = json.load(mediafile)
    else:
        media_options = {}        

    if show_details:
        detailsfile = open("details.txt", "w")

    stats = {}        
    engine = create_engine(db_url, echo=False, future=True)
    with Session(engine) as session:
        
        results = session.query(Item.filepath, sqlalchemy.func.avg(Item.filesize_mb)).filter(Item.mediatype == "tv").group_by(Item.filepath).order_by("filepath").all()
        
        if show_details:
            detailsfile.write(details_header() + "\n")
            
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
                acodecs = set()
                alang = set()
                clayouts = set()
                pixf = set()

                stats[path] = { "avg": int(_avg), "src": set(), "res": set(), "vcodecs": set() }
                
                #
                # process each episode
                #
                items: List[Item] = session.query(Item).options(joinedload(Item.audio)).filter(Item.filepath == path).all()
                if not items:
                    continue

                if show_details:
                    detailsfile.write(f"{path}:\n")

                for item in items:

                    if show_details:
                        detailsfile.write(details(item) + "\n")

                    if item.audio:
                        for a in item.audio:
                            acodecs.add(a.codec)
                            alang.add(a.lang)
                            clayouts.add(a.channel_layout)
                    
                    # filesizes
                    sizes.append(item.filesize_mb)
                    
                    pixf.add(item.pix_format)
                    
                    # season and episode numbers
                    se = extract_se(item.filename)
                    if len(se) == 2:
                        s, e = se
                        if season > 0 and season != s:
                            oop.append(item.filename)
                        eplist.extend(e)
                    else:
                        print(f"  * Unable to parse season/episode(s) from {item.filename} -- skipped")
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
                stats[path]["avg"] = int(np.average(sizes))

                mxe = np.max(eplist)
                egaps = set([e for e in range(1, mxe)]).difference(eplist)
                stats[path]["egaps"] = [str(gap) for gap in egaps]
                stats[path]["src"] = src
                stats[path]["res"] = res
                stats[path]["oop"] = oop
                stats[path]["vcodecs"] = codecs
                stats[path]["acodecs"] = acodecs
                stats[path]["alang"] = alang
                stats[path]["clayouts"] = clayouts
                stats[path]["pixformats"] = pixf
                
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
            
            if name in media_options:
                opts = media_options[name]
                if opts.get("locked", False):
                    # user has indicated the show is locked and just ignore it
                    print(f"{name} (skipped)")
                    continue
            else:
                media_options[name] = { "locked": False }
            
            print(f"{name}:")
            if report_codecs:
                if len(summary["vcodecs"]) > 1:
                    print(f"   Mixture of video codecs: {summary['vcodecs']}")
                    
            if len(summary["pixformats"]) > 1:
                print(f"   Mixture of pixel formats: {summary['pixformats']}")

            #
            # Report on inconsistent source (br, webdl) at series level
            #
            if "src" in summary and mixed_sources(summary["src"]):
                print(f"   Mixture of video sources: {summary['src']}")
            #
            # Report on inconsistent resolutions
            #
            if len(summary["res"]) > 1:
                print(f"   Mixture of resolutions: {summary['res']}")

            for season in seasons:
                report = ""

                if len(season["pixformats"]) > 1:
                        report += f"   Mixture of pixel formats: {season['pixformats']}\n"

                if "std" in season:
                    threshold = (season["std"] / season["avg"]) * 100
                    if season["std"] > season["min"] or threshold > 30.0:
                        report += f"     Inconsistent file sizes (stddev={season['std']}, min={season['min']}, max={season['max']}), avg={season['avg']}\n"
                else:
                    print(f"Unexpected missing data in {show}, Season {season['season']} - skipped")
                    continue
                #
                # Report on out of place episodes
                #
                if "oop" in season and len(season["oop"]):
                    report += "     Out of place: "
                    for oop in season["oop"]:
                        report += f"       {oop}"
                    report += "\n"
                #
                # Report on episode gaps
                #
                if "egaps" in season and len(season["egaps"]):
                    report += "     Missing: " + ",".join(season["egaps"]) + "\n"

                if "src" in season and mixed_sources(season["src"]):
                    report += f"     Sources: {season['src']}\n"
                    
                if report_codecs:
                    if len(season["vcodecs"]) > 1:
                        report += f"     Video codecs: {season['vcodecs']}\n"

                if len(season["res"]) > 1:
                    report += f"     Resolutions: {season['res']}\n"
#                if len(season["clayouts"]) > 1:
#                    report += f"     Channel layouts: {season['clayouts']}\n"

                if len(report) > 0:
                    report = f"   Season {season['season']}\n" + report
                    print(report)

    if show_details:
        detailsfile.close()

    with open("mediaopts.json", "w") as mediafile:
        json.dump(media_options, mediafile, indent=4)
    print("mediaopts.json updated.")
