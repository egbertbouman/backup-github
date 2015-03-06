import os
import sys
import json
import stat
import errno
import base64
import shutil
import pexpect
import urllib2
import argparse
import ConfigParser

from time import time
from subprocess import Popen, PIPE
from zipfile import ZipFile, ZIP_DEFLATED

GITHUB_API = "https://api.github.com"
GIT_CLONE_CMD = "git clone --quiet --mirror {url}"
REMOVE_AFTER = 7 * 24 * 3600 # Remove after 7 days


def zip_dir(dir, outputfilename, remove=False):
    dir_len = len(dir.rstrip(os.sep)) + 1
    with ZipFile(outputfilename, mode='w', compression=ZIP_DEFLATED) as zf:
        for dirname, subdirs, files in os.walk(dir):
            for filename in files:
                path = os.path.join(dirname, filename)
                entry = path[dir_len:]
                zf.write(path, entry)

    if remove:
        # Removing the directory on Windows can give an error in case of read-only files
        # Source: http://stackoverflow.com/questions/1213706/what-user-do-python-scripts-run-as-in-windows
        def handleRemoveReadonly(func, path, exc):
            excvalue = exc[1]
            if func in (os.rmdir, os.remove) and excvalue.errno == errno.EACCES:
                os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO) # 0777
                func(path)
            else:
                raise
        shutil.rmtree(dir, ignore_errors=False, onerror=handleRemoveReadonly)

def resolve_path(executable):
    if os.path.sep in executable:
        raise ValueError("Invalid filename: %s" % executable)
    path = os.environ.get("PATH", "").split(os.pathsep)
    # PATHEXT tells us which extensions an executable may have
    path_exts = os.environ.get("PATHEXT", ".exe;.bat;.cmd").split(";")
    has_ext = os.path.splitext(executable)[1] in path_exts
    if not has_ext:
        exts = path_exts
    else:
        # Don't try to append any extensions
        exts = [""]
    for d in path:
        try:
            for ext in exts:
                exepath = os.path.join(d, executable + ext)
                if os.access(exepath, os.X_OK):
                    return exepath
        except OSError:
            pass
    return None

def mirror_repo(url, output_dir, username, password):
    cmd = GIT_CLONE_CMD.format(url=url) + ' ' + output_dir
    child = pexpect.spawn(cmd)
    i = child.expect([pexpect.TIMEOUT, 'Username for', pexpect.EOF], timeout=300)

    if i == 0:
        child.terminate()
        raise Exception('Git timed out')
    elif i == 1:
        child.sendline(username)
        child.expect('Password for')
        child.sendline(password)
        child.expect(pexpect.EOF, timeout=300)
    child.close()

    return child.exitstatus if child.exitstatus != None else child.signalstatus

def backup(backupdir, organization, username, password):
    print 'Storing backup for', organization, 'to', backupdir

    if not os.path.exists(backupdir):
        print 'Directory', backupdir, 'does not exists, creating it now'
        os.makedirs(backupdir)

    print 'Fetching list of repositories..'
    request = urllib2.Request(GITHUB_API + '/orgs/' + organization + '/repos')
    if username != None and password != None:
        base64string = base64.encodestring('%s:%s' % (username, password)).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
    repsonse = urllib2.urlopen(request).read()
    repos = json.loads(repsonse)
    print 'Found', len(repos), 'repositories'

    repo_urls = {}
    for repo in repos[:]:
        repo_urls[repo['name']] = repo['clone_url']
        repo_urls[repo['name'] + '.wiki'] = repo['clone_url'][:-4] + '.wiki.git'

    for name, url in repo_urls.iteritems():
        ts = str(int(time()))
        print 'Backuping up', name + '..',
        output_dir = '%s/%s-%s-%s.git' % (backupdir, organization, name, ts)
        if mirror_repo(url, output_dir, username, password) != 0:
            print 'ERROR'
        else:
            zip_dir(output_dir, output_dir + '.zip', remove=True)
            print 'OK'

def clean_backup_dir(dir):
    remove_ts = time() - REMOVE_AFTER
    for dirname, subdirs, files in os.walk(dir):
        for filename in files:
            if filename.endswith('.git.zip'):
                ts = int(filename.split('-')[-1][:-8])
                if ts < remove_ts:
                    print 'Removing', filename
                    path = os.path.join(dirname, filename)
                    os.remove(path)

def main(argv):
    parser = argparse.ArgumentParser(add_help=False, description=('Backup a GitHub organization'))
    parser.add_argument('--help', '-h', action='help', default=argparse.SUPPRESS, help='show this help message and exit')

    group1 = parser.add_argument_group(title='File-based configuration')
    group1.add_argument('--config', '-c', help='Read configuration from file')

    group2 = parser.add_argument_group(title='Command line configuration')
    group2.add_argument('--dir', '-d', help='Directory in which to store the backup')
    group2.add_argument('--organization', '-o', help='GitHub organization for which to make a backup')
    group2.add_argument('--username', '-u', help='GitHub username')
    group2.add_argument('--password', '-p', help='GitHub password')


    try:
        args = parser.parse_args(sys.argv[1:])

        dir = args.dir
        organization = args.organization
        username = args.username
        password = args.password

        if args.config:
            config = ConfigParser.RawConfigParser()
            with open(args.config) as fp:
                config.readfp(fp)

            section = 'backup-github-organization'
            dir = config.get(section, 'dir')
            organization = config.get(section, 'organization')
            username = config.get(section, 'username')
            password = config.get(section, 'password')

        if not dir or not organization:
            parser.print_usage()
            raise ValueError('A directory and GitHub organization are required options')

        backup(dir, organization, username, password)
        clean_backup_dir(dir)

    except Exception, e:
        print 'Error:', str(e)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])

