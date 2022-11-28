
# mediascan / mediareport #

A set of scripts to scan your media library and report on possible issues.
The results of a scan are kept in a SQL database that you may use for your own needs as well.

---
## mediascan.py ##

**requirements**

* Python 3.10+
* ffprobe (part of ffmpeg package) installed and in current PATH
* Movie and Television media stored under different paths (not mixed).
* Television series must be storied in season folders using a standard season & episode naming convention, preferably the default used for Sonarr (S01E01).

Mediacan will scan all indicated paths for known media files, problem them for details, and log those details into a SQL database.  By default, you can use SQLite3 which doesn't require any additional installation.  If you choose, you may use any other SQL database supported by SQLAlchemy.

**configuration**

Configuration for both scripts is in _mediascan.json_.  It contains a list of media paths and the database configuration.

> You can specify as many paths as you like.

**path**   
- Full path to the root of your media folder for a specific type.  

**enabled**
- true or false, indicating if the path is to be scanned.  

**tags**
- (optional). List of tags to apply.  Each tag has a regex pattern. If the media being scanned matches that pattern then the tag is applied.  Multiple tags may be applied.  These tags are strictly for your benefit and are stored in the database for your use.


Example:

```
{
    "paths": [
    {
        "path" : "/mnt/merger/media/video/Movies",
        "enabled": true,
        "tags" : [
            {
                "pattern": ".*",
                "tag": "movie"
            }
        ]
    },
    {
        "path" : "/mnt/merger/media/video/Television",
        "enabled": true,
        "tags" : [
            {
                "pattern": ".*",
                "tag": "tv"
            }
        ]
    }
],
"database": [
    {
        "connect": "sqlite:///mediascan.db",
        "enabled": false
    },
    {
        "connect": "postgresql+pg8000://user:pass@myserver/mediascan",
        "enabled": true
    }
]
}

```



## mediareport.py ##
