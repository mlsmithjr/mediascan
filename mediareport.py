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
from mediascan import Item, Audio, Path
import numpy as np
import re
import yaml


episode_pattern = re.compile(r"S(\d+)E(\d+)", re.IGNORECASE)
episode_pattern_alt1 = re.compile(r"S(\d+)E(\d+)(-)(\d+)", re.IGNORECASE)
episode_pattern_alt2 = re.compile(r"S(\d+)((?:E\d+)+)", re.IGNORECASE)
episode_pattern_alt3 = re.compile(r"S(\d+)E(\d+)(-)E(\d+)", re.IGNORECASE)
season_pattern = re.compile(r"Season\ (\d+)", re.IGNORECASE)
show_pattern = re.compile(r"(/.+?)/Season\ \d+", re.IGNORECASE)
name_pattern = re.compile(r"^/.*/(.+)$", re.IGNORECASE)
trunc_pattern = re.compile(r"^.*(S\d+E\d+.*)", re.IGNORECASE)

sources = [ "bluray", "dvd", "webdl", "webrip", "sdtv", "hdtv"]


def sum_show(show_seasons: List[Item]) -> Dict:
    show_summary = {}
    show_summary["src"] = set()
    show_summary["res"] = set()
    show_summary["vcodecs"] = set()
    show_summary["pixformats"] = set()

    for show_season in show_seasons:
        show_summary["src"].update(show_season["src"])
        show_summary["res"].update(show_season["res"])
        show_summary["vcodecs"].update(show_season["vcodecs"])
        show_summary["pixformats"].update(show_season["pixformats"])
        
    return show_summary

def extract_se(filename):
    # try spanning patterns (00-01)
    se_match = episode_pattern_alt1.search(filename)
    if se_match and se_match.group(3) == "-":
        s = se_match.group(1)
        first = se_match.group(2)
        last = se_match.group(4)
#        last = re.compile(r"S\d+E\d+-(\d+)").search(filename).group(4)
        return (int(s), [int(first), int(last)])

    # try spanning patterns (E01-E02)
    se_match = episode_pattern_alt3.search(filename)
    if se_match and se_match.group(3) == "-":
        s = se_match.group(1)
        first = se_match.group(2)
        last = se_match.group(4)
#        last = re.compile(r"S\d+E\d+-(\d+)").search(filename).group(4)
        return (int(s), [int(first), int(last)])

    # try multi-episode pattern (E01E02E03...)
    se_match = episode_pattern_alt2.search(filename)
    if se_match:
        s = se_match.group(1)
        all = se_match.group(2)
        if len(all) > 3:
            eplist = all[1:].split("E")
            return (int(s), [int(e) for e in eplist])

    # Lastly, try the typical pattern
    se_match = episode_pattern.search(filename)
    if se_match:
        s = se_match.group(1)
        ep = se_match.group(2)
        return (int(s), [int(ep)])

    return ()                        

def extract_src(filename: str) -> Optional[str]:
    copy = filename.lower()
    for source in sources:
        if source in copy:
            return source
    return "???"

def mixed_sources(sources) -> bool:                
    if "bluray" in sources and len(sources) > 1:
        return True
    if "dvd" in sources and len(sources) > 1:
        return True
    return False

def details_header() -> str:
    return f"   {'Episode':65} {'Dur':>7} {'Size(mb)':>8} {'FPS':>5} {'Bit Rate'} {'Resolution'} {'Color':>10} {'Pixel Fmt':>12}"

def details(an_item: Item) -> str:
    trunc_match = trunc_pattern.search(an_item.filename)
    if trunc_match:
        partial = trunc_match.group(1)
    else:
        partial = an_item.filename
    item_details = f"   {partial:65} {an_item.duration:>7} {an_item.filesize_mb:>8} {an_item.fps:>5} {an_item.bit_rate or 0:>8} {an_item.width:>5}x{an_item.height:<4} {an_item.color_space or '':>10} {an_item.pix_format:>12}"
    return item_details

#
# main
#

if __name__ == "__main__":

    report_codecs = False
    show_details = False
    show_langdefaults = False
    
    if len(sys.argv) > 1:
        for arg in sys.argv:
            if arg == "-c":
                report_codecs = True
            elif arg == "-d":
                show_details = True
            elif arg == "-l":
                show_langdefaults = True

    ##
    # load configuration
    #
    with open("mediascan.yml", "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.Loader)

    for db in config["database"]:
        if db.get("enabled", True):
            db_url = db["connect"]
            break
    else:
        print("No enabled database configured")
        sys.exit(0)
        
    if os.path.exists("mediaopts.json"):
        with open("mediaopts.json", "r", encoding="utf-8") as mediafile:
            media_options = json.load(mediafile)
    else:
        media_options = {}

    if show_details:
        detailsfile = open("details.txt", "w", encoding="utf-8")

    stats = {}
    engine = create_engine(db_url, echo=False, future=True)
    with Session(engine) as session:

        results = session.query(Path).filter(Path.mediatype == "tv").order_by("filepath").all()
        #results = session.query(Item.filepath, sqlalchemy.func.avg(Item.filesize_mb)).filter(Item.mediatype == "tv").group_by(Item.filepath).order_by("filepath").all()

        if show_details:
            detailsfile.write(details_header() + "\n")

        for result in results:
            path = result.filepath

            #print(path)

            try:
                smatch = season_pattern.search(path)
                if smatch:
                    season_nr = int(smatch.group(1))
                else:
                    season_nr = 0

                if not season_nr:
                    continue

                eplist = []
                sizes = []
                bitrates = []
                codecs = set()
                oop = []
                res = set()
                src = set()
                acodecs = set()
                alang = set()
                clayouts = set()
                pixf = set()

                #
                # process each episode
                #
                items: List[Item] = session.query(Item).options(joinedload(Item.audio)).options(joinedload(Item.subtitle)).filter(Item.path == result).all()
                if not items:
                    continue

                stats[path] = { "avg": 0, "src": set(), "res": set(), "vcodecs": set(), "pixformats": set() }

                if show_details:
                    detailsfile.write(f"{path}:\n")

                for item in items:

                    if show_details:
                        detailsfile.write(details(item) + "\n")

                    if item.audio:
                        for a in item.audio:
                            acodecs.add(a.codec)
                            if a.isdefault:
                                alang.add(a.lang)
                            clayouts.add(a.channel_layout)
                    
                    sizes.append(item.filesize_mb)
                    if item.bit_rate:
                        bitrates.append(item.bit_rate)
                    pixf.add(item.pix_format)
                    
                    # season and episode numbers
                    se = extract_se(item.filename)
                    if len(se) == 2:
                        s, e = se
                        if season_nr > 0 and season_nr != s:
                            oop.append(item.filename)
                        eplist.extend(e)
                    else:
                        print(f"  * Unable to parse season/episode(s) from {item.filename} -- skipped")
                        continue

                    codecs.add(item.vcodec)
                    res.add(item.display_res)
                    src.add(extract_src(item.filename))

                #
                # store details
                #
                stats[path]["season"] = season_nr
                
                # file sizes
                stats[path]["std"] = int(np.std(sizes))
                stats[path]["max"] = np.max(sizes)
                stats[path]["min"] = np.min(sizes)
                stats[path]["avg"] = int(np.average(sizes))

                # bitrates
                if bitrates and len(bitrates) > 0:
                    stats[path]["bitstd"] = int(np.std(bitrates))
                    stats[path]["bitmax"] = np.max(bitrates)
                    stats[path]["bitmin"] = np.min(bitrates)
                    stats[path]["bitavg"] = int(np.average(bitrates))
                else:
                    stats[path]["bitstd"] = 0
                    stats[path]["bitmax"] = 0
                    stats[path]["bitmin"] = 0
                    stats[path]["bitavg"] = 0

                # the rest
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
#                traceback.print_exc()
                print(ex)
                print(f"** Unexpected error processing {path} -- skipping")            

        #
        # make a list of show titles and do the analysis
        #

        shows = set()
        for path in stats.keys():
            match = show_pattern.search(path)
            if match:
                shows.add(match.group(1))

        for show in sorted(shows):
            seasons = [v for k,v in stats.items() if k.startswith(show + "/")]
            #print(show)
            summary = sum_show(seasons)

            name = name_pattern.match(show).group(1)

            if name in media_options:
                opts = media_options[name]
                if opts.get("locked", False):
                    # user has indicated the show is locked so just ignore it
                    print(f"{name} (locked)")
                    continue
            else:
                # must be a new show so add a placeholder
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

            for season_nr in seasons:
                report = ""

                if len(season_nr["pixformats"]) > 1:
                        report += f"   Mixture of pixel formats: {season_nr['pixformats']}\n"

                if "std" in season_nr:
                    threshold = (season_nr["std"] / season_nr["avg"]) * 100
                    if season_nr["std"] > season_nr["min"] or threshold > 40.0:
                        report += f"     Inconsistent file sizes (stddev={season_nr['std']}, min={season_nr['min']}, max={season_nr['max']}), avg={season_nr['avg']}\n"
                else:
                    print(f"Unexpected missing data in {show}, Season {season_nr['season']} - skipped")
                    continue
                
                if "bitstd" in season_nr and season_nr["bitstd"] > 0:
                    threshold = (season_nr["bitstd"] / season_nr["bitavg"]) * 100
                    if season_nr["bitstd"] > season_nr["bitmin"] or threshold > 40.0:
                        report += f"     Inconsistent bit rates (stddev={season_nr['bitstd']}, min={season_nr['bitmin']}, max={season_nr['bitmax']}), avg={season_nr['bitavg']}\n"
                
                if show_langdefaults and "alang" in season_nr and len(season_nr["alang"]) > 1:
                    report += f"     Multiple audio languages set to default: {season_nr['alang']}\n"
                #
                # Report on out of place episodes
                #
                if "oop" in season_nr and len(season_nr["oop"]):
                    report += "     Out of place: "
                    for oop in season_nr["oop"]:
                        report += f"       {oop}"
                    report += "\n"
                #
                # Report on episode gaps
                #
                if "egaps" in season_nr and len(season_nr["egaps"]):
                    report += "     Missing: " + ",".join(season_nr["egaps"]) + "\n"

                if "src" in season_nr and mixed_sources(season_nr["src"]):
                    report += f"     Sources: {season_nr['src']}\n"
                    
                if report_codecs:
                    if len(season_nr["vcodecs"]) > 1:
                        report += f"     Video codecs: {season_nr['vcodecs']}\n"

                if len(season_nr["res"]) > 1:
                    report += f"     Resolutions: {season_nr['res']}\n"
#                if len(season["clayouts"]) > 1:
#                    report += f"     Channel layouts: {season['clayouts']}\n"

                if len(report) > 0:
                    report = f"   Season {season_nr['season']}\n" + report
                    print(report)

    if show_details:
        detailsfile.close()

    with open("mediaopts.json", "w", encoding="utf-8") as mediafile:
        json.dump(media_options, mediafile, indent=4)
    print("mediaopts.json updated.")
