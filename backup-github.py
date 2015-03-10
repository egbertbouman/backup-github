#!/usr/bin/env python
import os
import sys
import glob
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
from zipfile import ZipFile, ZIP_DEFLATED


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


class GitHubBackup(object):

    GITHUB_API_ORG_REPOS = "https://api.github.com/orgs/{organization}/repos"
    GITHUB_API_USR_REPOS = "https://api.github.com/users/{user}/repos"
    GITHUB_API_COMMITS = "https://api.github.com/repos/{organization_or_user}/{repo_name}/commits"
    GIT_CMD_CLONE = "git clone --quiet --mirror {url} {output_dir}"
    PRUNE_TIME = 7 * 24 * 3600 # Remove after 7 days

    def __init__(self, organization=None, username=None, password=None):
        if not username and not organization:
            raise ValueError('Missing username/organization')
        if organization and username and not password:
            raise ValueError('Missing password')
        self.username = username
        self.password = password
        self.account = organization or username
        self.is_organization = bool(organization)

    def _api_request(self, url):
        request = urllib2.Request(url)
        if self.password:
            base64string = base64.encodestring('%s:%s' % (self.username, self.password)).replace('\n', '')
            request.add_header("Authorization", "Basic %s" % base64string)

        try:
            response = urllib2.urlopen(request).read()
        except urllib2.HTTPError, error:
            response = error.read()

        response_dict = json.loads(response)
        if 'message' in response_dict:
            raise Exception(response_dict['message'])

        return response_dict

    def list_commits(self, repo_name):
        request_url = GitHubBackup.GITHUB_API_COMMITS.format(organization_or_user=self.account, repo_name=repo_name)
        return self._api_request(request_url)

    def list_repos(self):
        if self.is_organization:
            request_url = GitHubBackup.GITHUB_API_ORG_REPOS.format(organization=self.account)
        else:
            request_url = GitHubBackup.GITHUB_API_USR_REPOS.format(user=self.account)
        return self._api_request(request_url)

    def backup_repos(self, output_dir, progress_cb=None):
        ts = str(int(time()))

        for repo in self.list_repos():
            name = repo['name']

            if progress_cb:
                progress_cb(name, 0)

            skip = False
            commits = self.list_commits(name)
            short_sha1 = commits[0]['sha'][:7] if commits else None
            for filename in glob.glob(os.path.join(output_dir, '*.git.zip')):
                if short_sha1 == filename.split('-')[-2]:
                    skip = True
                    break

            if not skip:
                repo_output_dir = '%s/%s-%s-%s-%s.git' % (output_dir, self.account, name, short_sha1, ts)
                ret_code = self.backup_repo(repo['clone_url'], repo_output_dir)

            if progress_cb:
                progress_cb(repo['name'], (1 if ret_code == 0 else -1) if not skip else -2)

    def backup_repo(self, url, output_dir):
        cmd = GitHubBackup.GIT_CMD_CLONE.format(url=url, output_dir=output_dir)
        child = pexpect.spawn(cmd)
        i = child.expect([pexpect.TIMEOUT, 'Username for', pexpect.EOF], timeout=300)

        if i == 0:
            child.terminate()
            raise Exception('A timeout occurred while cloning' + url)
        elif i == 1:
            child.sendline(self.username)
            child.expect('Password for')
            child.sendline(self.password)
            child.expect(pexpect.EOF, timeout=300)
        child.close()

        ret_code = child.exitstatus if child.exitstatus is not None else child.signalstatus
        if ret_code == 0:
            zip_dir(output_dir, output_dir + '.zip', remove=True)
        return ret_code

    def prune_backups(self, dir):
        # Get the current backups and sort by timestamp
        backups = glob.glob(os.path.join(dir, '*.git.zip'))
        backups = [(int(path.split('-')[-1][:-8]), path) for path in backups]
        backups.sort()

        # Remove backups that are older than PRUNE_TIME, except when there are no
        # other backups available for the repository in question.
        remove_ts = time() - GitHubBackup.PRUNE_TIME
        for ts, path in backups:
            if ts < remove_ts:
                pattern = '-'.join(path.split('-')[:-2]) + '-???????-??????????.git.zip'
                if len(glob.glob(pattern)) > 1:
                    os.remove(path)


def main(argv):
    parser = argparse.ArgumentParser(add_help=False, description=('Backup a GitHub account'))
    parser.add_argument('--help', '-h', action='help', default=argparse.SUPPRESS, help='Show this help message and exit')

    group1 = parser.add_argument_group(title='File-based configuration')
    group1.add_argument('--config', '-c', help='Read configuration from file')

    group2 = parser.add_argument_group(title='Command line configuration')
    group2.add_argument('--dir', '-d', help='Directory in which to store the backup')
    group2.add_argument('--organization', '-o', help='GitHub organization for which to make a backup')
    group2.add_argument('--username', '-u', help='GitHub username. If no organization is provided, this account will be backed up.')
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

            section = 'backup-github'
            dir = config.get(section, 'dir')
            organization = config._sections[section].get('organization', None)
            username = config.get(section, 'username')
            password = config._sections[section].get('password', None)

        if not dir or not (username or organization):
            parser.print_usage()
            raise ValueError('directory and username/organization are required options')

        print 'Storing backup for', (organization or username), 'to', dir
        if not os.path.exists(dir):
            print 'Directory', dir, 'does not exists, creating it now'
            os.makedirs(dir)

        backup = GitHubBackup(organization, username, password)

        def progress_cb(name, state):
            if state == 0:
                print 'Backuping up', name + '..',
            elif state == 1:
                print 'OK'
            elif state == -2:
                print 'SKIPPING'
            else:
                print 'ERROR'

        backup.backup_repos(dir, progress_cb)
        backup.prune_backups(dir)

    except Exception, e:
        print 'Error:', str(e)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
