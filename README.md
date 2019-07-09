# cinder-easy-backup

Create backups of all available cinder-volumes unless defined otherwise

### Setup

```
apt-get install python3-venv
git clone git@github.com:omniga-gmbh-co-kg/cinder-easy-backup.git
cd cinder-easy-backup
python3 -m venv venv
. venv/bin/activate
pip install pip --upgrade
pip install -r requirements.txt
```

## Getting Started

Allow User Access to Project (e.g. User 'Admin' on Project 'fd')
```
openstack role add --project office admin --user admin
```

Start Backup
```
. venv/bin/activate
python cinder-easy-backup.py
```

### Config

**Disable Backups** <br>
As a safety Feature, every Volume of every Instance that is not explicitly excluded from Backups, will be backed up. <br>
To exclude an Instance or a Volume from Backups, add a Metadata attribute `backup=false`


**backup.excludes.projects** <br>
Exclude full Projects from Backup, supersedes Config in Metadata.

**backup.interval** <br>
  *default:* the inimum age of backups in days, before new backups are created <br>
  *project_override:* project specific intervals (supersedes default)

**backup.post_script** <br>
Script that get executed after all operations for the current project are finished

**backup.retention** <br>
  *default:* how many backups to keep of each volume
  *project_override:* project_specific retention (supersedes default)

**backup.wait_for_completion** <br>
  `true`  Wait for each Backup to complete before starting the next one<br>
  `false` Start all Backups simultaneously
<br>
  *default:* default behaviour for all projects <br>
  *project_override:* project_specific behaviour

**log** <br>
  *file:* Logfile Location <br>
  *log.level:* Loglevel for File-Log, possible Values *CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET*

**auth.env_vars** <br>
Environment Variables used for authentication with shade (formerly in openrc)
