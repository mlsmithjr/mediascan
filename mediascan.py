#!python3

import json
import subprocess
import os
import sqlite3
import sys
from typing import Optional, Dict

EXTENSIONS = [".mkv", ".mp4", ".avi", ".m4v"]

FFPROBE_PATH="/usr/bin/ffprobe"


class MediaInfo:
    # pylint: disable=too-many-instance-attributes

    def __init__(self, info: Optional[Dict]):
        self.valid = info is not None
        if not self.valid:
            return
        self.info = info
        self.path = info['path']
        self.vcodec = info['vcodec']
        self.stream = info['stream']
        self.res_height = info['res_height']
        self.res_width = info['res_width']
        self.runtime = info.get('runtime', 0)
        self.filesize_mb = info['filesize_mb']
        self.fps = info['fps']
        self.color_space = info['color_space']
        self.pix_fmt = info['pix_fmt']
        self.audio = info['audio']
        self.subtitle = info['subtitle']

    def default_audio(self) -> Optional[Dict]:
        if len(self.audio) == 1:
            return self.audio[0]
        for a in self.audio:
            if a["default"] == 1:
                return a
        return None

    def runtime_str(self):
        if self.runtime > 3600:
            hh = int(self.runtime / 3600)
            mm = int((self.runtime % 3600) / 100)
            return f"{hh}:{mm}"

    def __repr__(self):
        return f"{self.path}, {self.vcodec=}, {self.stream=}, {self.res_width}x{self.res_height}, {self.runtime_str()=}, {self.audio=}"


def parse_ffmpeg_details_json(_path, info):
    minone = MediaInfo(None)
    minfo = {'audio': [], 'subtitle': []}
    if 'streams' not in info:
        return minone
    video_found = False
   
    default_lang = "???"
    for stream in info['streams']:
        if stream['codec_type'] == 'video' and not video_found:
            video_found = True
            minfo['path'] = _path
            minfo['vcodec'] = stream['codec_name']
            minfo['stream'] = str(stream['index'])
            minfo['res_width'] = stream['width']
            minfo['res_height'] = stream['height']
            minfo['filesize_mb'] =int(os.path.getsize(_path) / (1024 * 1024))
            fr_parts = stream['r_frame_rate'].split('/')
            fr = int(int(fr_parts[0]) / int(fr_parts[1]))
            minfo['fps'] = str(fr)
            minfo['color_space'] = stream.get('color_space', None)
            minfo['pix_fmt'] = stream['pix_fmt']
            if 'duration' in stream:
                minfo['runtime'] = int(float(stream['duration']) / 60)  # convert to whole minutes
            else:
                if 'tags' in stream:
                    for name, value in stream['tags'].items():
                        if name[0:8] == 'DURATION':
                            hh, mm, ss = value.split(':')
                            duration = (int(float(hh)) * 60) + (int(float(mm)))  # * 60) + int(float(ss))
                            minfo['runtime'] = duration
                            break
            if "tags" in stream and "language" in stream["tags"]:
                default_lang = stream["tags"]["language"]

        elif stream['codec_type'] == 'audio':
            audio = {"lang": default_lang}
            audio['stream'] = str(stream['index'])
            audio['format'] = stream['codec_name']
            audio['default'] = 0
            audio['channel_layout'] = stream.get('channel_layout', None)
            audio['bit_rate'] = stream.get('bit_rate', None)
            if 'disposition' in stream:
                if 'default' in stream['disposition']:
                    audio['default'] = stream['disposition']['default']
            if 'tags' in stream:
                if 'language' in stream['tags']:
                    audio['lang'] = stream['tags']['language']
                else:
                    # derive the language
                    for name, value in stream['tags'].items():
                        if name[0:9] == 'DURATION-':
                            lang = name[9:]
                            audio['lang'] = lang
                            break
            minfo['audio'].append(audio)
        elif stream['codec_type'] == 'subtitle':
            sub = {"lang": default_lang}
            sub['stream'] = str(stream['index'])
            sub['format'] = stream.get('codec_name', None)
            sub['default'] = 0
            if 'disposition' in stream:
                if 'default' in stream['disposition']:
                    sub['default'] = stream['disposition']['default']
            if 'tags' in stream:
                if 'language' in stream['tags']:
                    sub['lang'] = stream['tags']['language']
                else:
                    # derive the language
                    for name, value in stream['tags'].items():
                        if name[0:9] == 'DURATION-':
                            lang = name[9:]
                            sub['lang'] = lang
                            break
            minfo['subtitle'].append(sub)
    return MediaInfo(minfo)


def getinfo(filepath: str):
    args = [FFPROBE_PATH, '-v', '1', '-show_streams', '-print_format', 'json', '-i', filepath]
    with subprocess.Popen(args, stdout=subprocess.PIPE) as proc:
        output = proc.stdout.read().decode(encoding='utf8')
        info = json.loads(output)
        return parse_ffmpeg_details_json(filepath, info)


def update_db(root:str, filename: str, info: MediaInfo):
    global cur

    audio = info.audio
    if not audio:
        print(f"Skipping {info.path} due to missing audio track")
    else:
        itemid = -1
        p = os.path.join(root, filename)
        if p in existing_files:
            itemid = existing_files[p]["id"]
        if itemid != -1:
            cur.execute("delete from audio where itemid = ?", (itemid,))
            cur.execute("delete from subtitle where itemid = ?", (itemid,))

            x = cur.execute("update item set filename=?, filepath=?, vcodec=?, height=?, width=?, filesize_mb=?, fps=?, color_space=?, pix_format=?, duration=?, last_modified=? "
                        "where id = ?", 
                (filename, root, info.vcodec, info.res_height, info.res_width, info.filesize_mb, info.fps, info.color_space, info.pix_fmt, info.runtime, os.path.getmtime(p), itemid))
        else:
            cur.execute("insert into item ('filename','filepath','vcodec','height','width','filesize_mb','fps','color_space','pix_format','duration','last_modified') "
                        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                (filename, root, info.vcodec, info.res_height, info.res_width, info.filesize_mb, info.fps, info.color_space, info.pix_fmt, info.runtime, os.path.getmtime(p)))
            itemid = cur.lastrowid
        segments = []

        # make sure there is always a default audio track
        if len(audio) == 1:
            audio[0]['default'] = 1

        for a in audio:
            a = (itemid, a['lang'], a['format'], a['channel_layout'], a['default'])
            segments.append(a)
        cur.executemany("insert into audio ('itemid','lang','codec','channel_layout','isdefault') values (?,?, ?, ?, ?)", segments)

        segments = []
        for s in info.subtitle:
            s = (itemid, s['lang'], s['format'], s['default'])
            segments.append(s)
        cur.executemany("insert into subtitle ('itemid','lang','format','isdefault') values (?, ?, ?, ?)", segments)



def dig(start: str):
    global mode

    for root, _, files in os.walk(start):
#        print(root)
        for file in files:
            if file.startswith("."):
                continue
            if file[-4:] in EXTENSIONS:
                try:
                    p = os.path.join(root, file)
                    
                    if p in existing_files:

                        # make sure it was changed before we reprocess

                        last_mod = os.path.getmtime(p)
                        db_last_mod = existing_files[p]["last_mod"]
                        if last_mod == db_last_mod:
                            continue
                    
                    info = getinfo(p)
                    if info.valid:
                        print(f"  {file}")
                        update_db(root, file, info)
                except Exception as ex:
                    print(" " + os.path.join(root, file))
                    raise ex
                
        con.commit()

if __name__ == "__main__":

    global con, cur, existing_files, mode

    mode = "add"

    if len(sys.argv) > 1:
        if sys.argv[1] == "--refresh":
            mode = "refresh"
            print("running in refresh mode")

    con = sqlite3.connect("mediascan.db")
    cur = con.cursor()
    
    # load all existing files and database IDs in advance to speed things up
    existing_files = {}
    results = cur.execute("select id, filename, filepath, last_modified from item")
    for result in results:
        id, filename, filepath, last_mod = result
        existing_files[os.path.join(filepath, filename)] =  { "id":id, "last_mod":last_mod } 
    
    for start in ["/mnt/merger/media/video/Television", "/mnt/merger/media/video/Mark", "/mnt/merger/media/video/Movies", "/mnt/merger/media/video/anime/movies", "/mnt/merger/media/video/kaiju"]:
        dig(start)

    # finally, purge any files no longer on disk but in the database
    for p in existing_files.keys():
       if not os.path.exists(p):
           cur.execute("delete from item where id=?", (existing_files[p]["id"],))
           print(f"removed {p}")

    con.commit()
    con.close()


