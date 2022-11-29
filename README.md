
# mediascan / mediareport #

A set of scripts to scan your media library and report on possible issues.
The results of a scan are kept in a SQL database that you may use for your own needs as well.

These scripts ***do not*** make changes to your content.  They only read it, and store results in a given SQL database.

Feel free to suggest other reporting metrics that are useful (and possible).


---
**requirements**

* Python 3.10+
* ffprobe (part of ffmpeg package) installed and in current PATH
* Movie and Television media stored under different paths (not mixed).
* Television series must be storied in season folders using a standard season & episode naming convention, preferably the default used for Sonarr (S01E01).

Mediacan will scan all indicated paths for known media files, problem them for details, and log those details into a SQL database.  By default, you can use SQLite3 which doesn't require any additional installation.  If you choose, you may use any other SQL database supported by SQLAlchemy.

**configuration**

Configuration for both scripts is in _mediascan.yml_.  It contains a list of media paths and the database configuration.

### paths ###
---


|  Setting        | Description     |
|--------------|---------------------------------------|
| **path**     | Full path to the root of the media folder. You can have as many paths as you like. |
| **enable**   | _true_ or _false_, indicating if the path is to be scanned |
| **type** | Value is either **tv** or **movie** and is required for reporting to work correctly. |
| **tags** | (optional). List of tags to apply.  Each tag has a regex pattern. If the media being scanned matches that pattern then the tag is applied.  Multiple tags may be applied.  These tags are strictly for your benefit and are stored in the database for your use.  |


## database ##
---
You only need 1 database connection given.  There are 2 provided here to show alternate examples, but only one is enabled.  On first run if the database tables are missing they will be created automatically.

|  Setting        | Description     |
|--------------|---------------------------------------|
| **connect**  | This is the SQLAlchemy-compatible connection to your database. All you need is the connection string here any any optional driver installed to support it. |
| **enabled** | _true_ or _false_, good to test with alternate databases without rewriting config. |

*    *sqlite:///mediascan.db* will store the database in the current directory.

*    *sqlite:////foo/bar/mediascan.db* will store the database in the /foo/bar 
directory.
*    *postgresql+pg8000://user:pass@myserver/mediascan* Will connect to Postgres on host *myserver* using *user* and *pass* and database *mediascan*.  Note the database must already exist and be owned by the given user.  Also, the pg8000 package must be installed to support database connectivity.
---

### Example _mediascan.yml_: ###

```yaml
paths:
  - path: "/mnt/merger/media/video/Television"
    enabled: true
    type: tv
    tags:
      - pattern: ".*"
        tag: "tv"
  - path: "/mnt/merger/media/video/Movies"
    enabled: true
    type: movie
    tags:
      - pattern: ".*"
        tag: "movie"
  - path: "/mnt/merger/media/video/anime"
    enabled: true
    type: tv

database:
  - connect: "sqlite:///mediascan.db"
    enabled: false

  - connect: "postgresql+pg8000://user:pass@myserver/mediascan"
    enabled: true

```

---

## mediascan.py ##

Run:
```
python3 mediascan.py
```
This will start the scan.  You will see each item as it is being processed. If you have a large collection it may take quite a while to finish.  This is because it is reading the header of each file to get technical details out for the analysis.  
You can stop the scan at any time with ctrl-c and it will pick up where it left off on the next run.  

After the initial run, the scan will detect and only process changed files - making it much faster and easier to keep your database up to date.

## mediareport.py ##
The report using data from the database collected by mediascan only.  No filesystem is accessed.

```
python3 mediareport.py [-c] [-d]
```

Run the analysis on database collected in the database.  Various hard-coded patterns are checked and reported.

  * -c will cause the analysis to report on video codec use. It is off by default since reporting on mixed codecs isn't very helpful to most people.
  * -d will generated a detail report of all media to **details.txt**. If you will not be using the database for your own ad-hoc queries you can use this report to look at the same details the analysis is calling out.

> After each run the report creates/updates a file called mediaopts.json.  You can optionally edit this file and set the *locked* flag to *true* for any show you want to avoid reporting on.  For example, shows you've audited and "cleared" of issues so they don't clutter the report.

  ---
## Report Callouts ##

The report looks for patterns that may be problematic in the collection.  Currently only TV shows are analyzed in the report, but the database contains details of TV and Movies.

Sample:
```txt
My Messed Up Show:
    Mixture of pixel formats: {'yuv420p10le', 'yuv420p'}
    Mixture of video sources: {'webdl', 'bluray'}
    Mixture of resolutions: {808, 1080}
    Season 1
      Mixture of pixel formats: {'yuv420p10le', 'yuv420p'}
      Inconsistent file sizes (stddev=579, min=577, max=2690), avg=2132
      Resolutions: {808, 1080}
      Missing: 5,8
    Season 2
      Out of place: 6
      Mixture of video sources: {'webdl', 'bluray'}
      Mixture of video codecs: {'hevc', 'h264'}

```

Show-level inconsistencies are reporting on first, then each season is broken down separately.

Missing
> Episodes that are missing from each season.  Detection is based on episode 01 as the start and the highest episode in the collection as the end.  Any gaps in between are reported. This means that missing episodes beyond the highest number you have will not be detected.  Specials are not gap checked.

Mixture of pixel formats
> This identifies inconsistency of formats that could be problematic to some clients.  In the sample above we see both 8- and 10-bit formats present. For most modern streaming clients this shouldn't be a problem but for older TVs it may help isolate playback issues

Mixture of video sources
> This points out inconsistencies in where the material came from, helpful in finding and replacing those lower-quality webrips in a collection of bluray rips.

Resolutions
> Multiple resolutions were detected.  Depending on the encoder you will often find oddball resolutions mixed in with standard ones.  Usually they aren't a problem but a perfectionist would probably want to fix.

Inconsistent file sizes
> This is a best-guess detection of potential quality inconsistencies. The reported numbers are standard deviation, minimum, maximum, and average. This only shows up if the formula is triggered, which is currently: **((stddev / avg) * 100) > 30.0**. Often this is a false positive because several factors could account for file size gaps, such as a mix of h264- and h265-encoded episodes, double-length episodes, or shorter than typical episodes.  Most likely focusing on the minimum and average values is most useful.

Out of place
> Episodes in the wrong season folder based on filename.

Mixture of video codecs (if using -c)
> Shows inconsistent encoding. Not typically useful to most people but can be optionally reported for others.




