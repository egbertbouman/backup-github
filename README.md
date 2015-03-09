# backup-github

Script for backing up an organization's GitHub repositories.

### Dependencies
* Python 2.7+
* pexpect

You can install Pexpect using pip

    pip install pexpect


### Usage
```
usage: backup.py [--help] [--config CONFIG] [--dir DIR]
                 [--organization ORGANIZATION] [--username USERNAME]
                 [--password PASSWORD]

Backup a GitHub account

optional arguments:
  --help, -h            show this help message and exit

File-based configuration:
  --config CONFIG, -c CONFIG
                        Read configuration from file

Command line configuration:
  --dir DIR, -d DIR     Directory in which to store the backup
  --organization ORGANIZATION, -o ORGANIZATION
                        GitHub organization for which to make a backup
  --username USERNAME, -u USERNAME
                        GitHub username
  --password PASSWORD, -p PASSWORD
                        GitHub password
```

### Example backup.conf
```
[backup-github]
dir = your_backup_dir
organization = your_organization
username = your_personal_access_token
password = x-oauth-basic
```
