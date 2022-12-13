#!python3

import datetime
import json
import subprocess
import os
import sys
import re
from functools import cache
from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, inspect
import sqlalchemy
from sqlalchemy.orm import declarative_base, joinedload
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import Session, relationship

from typing import Optional, Dict
import yaml



EXTENSIONS = [".mkv", ".mp4", ".avi", ".m4v"]

FFPROBE_PATH="ffprobe"

Base = declarative_base()

SERIES_REGEX = re.compile(r"(.*)\.S(\d+)E(\d+)")
show_pattern = re.compile(r".*/(.+?)/Season\ \d+", re.IGNORECASE)

    
class Path(Base):
    __tablename__ = "path"

    id = Column(Integer, primary_key=True)
    filepath = Column(String(200), nullable=False, index=True)
    title = Column(String(200), nullable=True)
    mediatype = Column(String(5), nullable=False)

class Item(Base):
    __tablename__ = "item"
    id = Column(Integer, primary_key=True)
    pathid = Column(Integer, ForeignKey("path.id", ondelete='CASCADE'), nullable=False)
    filename = Column(String(300), nullable=False, index=True)
    vcodec = Column(String(10), nullable=False)
    filesize_mb = Column(Integer)
    height = Column(String(5))
    width = Column(String(5))
    duration = Column(Integer)
    fps = Column(String(7))
    color_space = Column(String(15))
    pix_format = Column(String(15))
    bit_rate = Column(Integer())
    last_modified = Column(DateTime)
    tag = Column(String(30))
    
    audio = relationship("Audio", back_populates="item", cascade="all, merge, delete-orphan", passive_deletes=True)
    subtitle = relationship("Subtitle", back_populates="item", cascade="all, merge, delete-orphan", passive_deletes=True)
    path = relationship("Path")

class Audio(Base):
    __tablename__ = "audio"
    id = Column(Integer, primary_key=True)
    itemid = Column(Integer, ForeignKey("item.id", ondelete='CASCADE'), nullable=False)
    lang = Column(String(10), index=True)
    codec = Column(String(15), index=True)
    channel_layout = Column(String(15))
    bit_rate = Column(Integer())
    isdefault = Column(Integer)
    item = relationship("Item", back_populates="audio")

class Subtitle(Base):
    __tablename__ = "subtitle"
    id = Column(Integer, primary_key=True)
    itemid = Column(Integer, ForeignKey("item.id", ondelete='CASCADE'), nullable=False)
    lang = Column(String(10), index=True)
    format = Column(String(30))
    isdefault = Column(Integer)
    item = relationship("Item", back_populates="subtitle")

##
# Define some helpful views here. They aren't used in the code but they are in the DB to use for additional reporting, dashboards, etc as needed.
##
item_audio_view_sql = [
    "CREATE VIEW item_audio_view AS ",
    "SELECT item.id, path.title, path.filepath, path.mediatype, item.vcodec, item.filesize_mb, item.height, item.width, item.duration, item.bit_rate as v_bitrate, item.fps, item.color_space, item.pix_format, item.last_modified, item.tag, item.filename, audio.codec AS audio_codec, audio.channel_layout, audio.bit_rate as a_bitrate, audio.lang ",
    "FROM item ",
    "JOIN path ON item.pathid = path.id ",
    "JOIN audio ON audio.itemid = item.id"
]
item_subtitle_view_sql = [
    "CREATE VIEW item_subtitle_view AS ",
    "SELECT item.id, path.title, path.filepath, path.mediatype, item.vcodec, item.filesize_mb, item.height, item.width, item.duration, item.fps, item.color_space, item.pix_format, item.last_modified, item.tag, item.filename, subtitle.lang ",
    "FROM item ",
    "JOIN path ON item.pathid = path.id ",
    "JOIN subtitle ON subtitle.itemid = item.id"
]
 
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
        self.bit_rate = info['bit_rate']

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


def get_filemodtime(p : str):
    mtime = os.path.getmtime(p)
    return datetime.datetime.fromtimestamp(mtime)


def getinfo(filepath: str):
    args = [FFPROBE_PATH, '-v', '1', '-show_streams', '-print_format', 'json', '-i', filepath]
    with subprocess.Popen(args, stdout=subprocess.PIPE) as proc:
        output = proc.stdout.read().decode(encoding='utf8')
        info = json.loads(output)
        return parse_ffmpeg_details_json(filepath, info)

@cache
def compiled_pattern(pattern: str) -> Optional[re.Pattern]:
    r = re.compile(pattern)
    return r

@cache
def fetch_or_create_dbpath(filepath: str, mediatype: str):
    thepath = session.query(Path).filter(Path.filepath == filepath).first()
    if not thepath:
        thepath = Path()
        thepath.filepath = filepath
        thepath.mediatype = mediatype
        match = show_pattern.search(filepath)
        if match:
            thepath.title = match.group(1)

    return thepath
    

def match_tag(p: str, path: Dict):

    if "tags" not in path:
        return None

    for tag in path.get("tags"):
        r = compiled_pattern(tag["pattern"])
        if r.match(p):
            return tag["tag"]
    return None

def store(root: str, filename: str, info: MediaInfo, path: Dict):
    global session

    audio = info.audio
    if not audio:
        print(f"Skipping {info.path} due to missing audio track")
    else:
        itemid = -1
        p = os.path.join(root, filename)
        if p in existing_files:
            itemid = existing_files[p].id
            dbpath = existing_files[p].path
            
        if itemid != -1:
            item = session.get(Item, itemid)
            item.audio.clear()
            item.subtitle.clear()
            session.flush()

            item.vcodec = info.vcodec
            item.height = info.res_height
            item.width = info.res_width
            item.filesize_mb = info.filesize_mb
            item.fps = info.fps
            item.color_space = info.color_space
            item.pix_format = info.pix_fmt
            item.duration = info.runtime
            item.bit_rate = info.bit_rate
            item.last_modified = get_filemodtime(p)
            item.tag = match_tag(p, path)
            
        else:
            item = Item()

            thepath = fetch_or_create_dbpath(root, path["type"])
            # if not thepath:
            #     thepath = Path()
            #     item.path = thepath
            #     item.path.filepath = root
            #     item.path.mediatype = path["type"]

            item.path = thepath

            item.filename = filename
            item.vcodec = info.vcodec
            item.height = info.res_height
            item.width = info.res_width
            item.filesize_mb = info.filesize_mb
            item.fps = info.fps
            item.color_space = info.color_space
            item.pix_format = info.pix_fmt
            item.duration = info.runtime
            item.bit_rate = info.bit_rate
            item.last_modified = get_filemodtime(p)
            item.tag = match_tag(p, path)
            session.add(item)

###        session.flush()

        # make sure there is always a default audio track
        if len(audio) == 1:
            audio[0]['default'] = 1

        for a in audio:
            a = Audio(lang=a['lang'], codec=a['format'], channel_layout=a['channel_layout'], isdefault=a['default'], bit_rate=a['bit_rate'])
            item.audio.append(a)

        for s in info.subtitle:
            s = Subtitle(lang=s['lang'], format=s['format'], isdefault=s['default'])
            item.subtitle.append(s)

#        session.merge(item)
        session.flush()


def dig(path: Dict):
    global mode

    root = path["path"]

    for root, subdir, files in os.walk(root):
        for file in files:
            if file.startswith(".") or os.path.isdir(file):
                continue
            if file[-4:] in EXTENSIONS:
                try:
                    p = os.path.join(root, file)
                    
                    if p in existing_files:

                        # make sure it was changed before we reprocess

                        last_mod = get_filemodtime(p)
                        db_last_mod = existing_files[p].last_modified
                        if last_mod == db_last_mod:
                            continue
                    
                    info = getinfo(p)
                    if info.valid:
                        print(f"  {file}")
                        store(root, file, info, path)
                except Exception as ex:
    #                print(" " + os.path.join(root, file))
                    print(file)
                    raise ex
                
        session.commit()

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
            minfo['bit_rate'] = stream.get('bit_rate', None)
            if minfo['bit_rate']:
                minfo['bit_rate'] = int(int(minfo['bit_rate']) / 1024)
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
                        if name == 'BPS' and minfo['bit_rate'] == None:
                            minfo['bit_rate'] = int(int(value) / 1024)
            if "tags" in stream and "language" in stream["tags"]:
                default_lang = stream["tags"]["language"]

        elif stream['codec_type'] == 'audio':
            audio = {"lang": default_lang}
            audio['stream'] = str(stream['index'])
            audio['format'] = stream['codec_name']
            audio['default'] = 0
            chlayout = stream.get('channel_layout', None)
            if not chlayout:
                chlayout = str(stream.get('channels', 0)) + " channels"
            audio['channel_layout'] = chlayout
            audio['bit_rate'] = stream.get('bit_rate')

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


if __name__ == "__main__":

    global engine, session, existing_files, mode

    mode = "add"

    if len(sys.argv) > 1:
        if sys.argv[1] == "--refresh":
            mode = "refresh"
            print("running in refresh mode")

    ##
    # load configuration
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

    paths = config.get("paths", [])
    if len(paths) == 0:
        print("No paths defined to scan")
        sys.exit(0)
        
    ##
    # connect to database and create tables, if missing
    #
    engine = create_engine(db_url, echo=False, future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:

        if not inspect(engine).has_table("item_audio_view"):
            session.execute(text(''.join(item_audio_view_sql)))

        if not inspect(engine).has_table("item_subtitle_view"):
            session.execute(text(''.join(item_subtitle_view_sql)))
    
        if mode == "refresh":
            # force everything to re-parse
            existing_files = dict()
        else:
            # load all existing files and database IDs in advance to speed things up
            existing_files = dict()
#            stmt = select(Item)
#            results = session.scalars(stmt)
            results = session.query(Item).options(joinedload(Item.path)).all()

            for result in results:
                existing_files[os.path.join(result.path.filepath, result.filename)] =  result
        
        for path in paths:
            if path.get("enabled", True):
                print(path["path"])
                dig(path)

        # finally, purge any records in the database whose file no longer exists
        for p, item in existing_files.items():
            if not os.path.exists(p):
                session.delete(item)
                print(f"removed {p} from database")
        # and purge missing folders from DB
        for dir in session.query(Path).all():
            if not os.path.exists(dir.filepath):
                session.delete(dir)

        session.commit()
    
    engine.dispose()


