# Python imports
import os
import copy

# Dulwich imports
from dulwich.repo import Repo as DRepo
from dulwich.client import get_transport_and_path
from dulwich.index import build_index_from_tree

# Local imports
from . import utils
from . import auth
from .exceptions import InvalidRemoteUrl


# Exports
__all__ = ('Gittle',)


class Gittle(object):
    DEFAULT_BRANCH = 'master'
    DEFAULT_MESSAGE = '**No Message**'
    DEFAULT_USER_INFO = {
        'name': None,
        'email': None,
    }

    HIDDEN_REGEXES = [
        # Hide git directory
        r'./.git/',
    ]

    def __init__(self, repo_or_path, origin_uri=None, auth=None, *args, **kwargs):
        if isinstance(repo_or_path, DRepo):
            self.repo = repo_or_path
        elif isinstance(repo_or_path, basestring):
            self.repo = DRepo(repo_or_path)
        else:
            raise Exception('Gittle must be initialized with either a dulwich repository or a string to the path')

        # Set path
        self.path = self.repo.path

        # The remote url
        self.origin_uri = origin_uri

        # Build ignore filter
        self.hidden_regexes = copy.copy(self.HIDDEN_REGEXES)
        self.hidden_regexes.extend(self._get_ignore_regexes())
        self.ignore_filter = utils.path_filter_regex(self.hidden_regexes)
        self.filters = [
            self.ignore_filter,
        ]

        # Get authenticator
        if auth:
            self.authenticator = auth
        else:
            self.auth(*args, **kwargs)

    def auth(self, *args, **kwargs):
        self.authenticator = auth.GittleAuth(*args, **kwargs)
        return self.authenticator

    # Generate a branch selector (used for pushing)
    def _wants_branch(self, branch_name=None):
        branch_name = branch_name or self.DEFAULT_BRANCH

        def wants_func(old):
            refs_key = "refs/heads/%s" % branch_name
            return {
                refs_key: self.repo.refs["HEAD"]
            }
        return wants_func

    def _get_ignore_regexes(self):
        gitignore_filename = os.path.join(self.path, '.gitignore')
        if not os.path.exists(gitignore_filename):
            return []
        lines = open(gitignore_filename).readlines()
        globers = map(lambda line: line.rstrip(), lines)
        return utils.globers_to_regex(globers)

    # Get the absolute path for a file in the git repo
    def abspath(self, repo_file):
        return os.path.join(self.path, repo_file)

    @property
    def last_commit(self):
        return self.repo[self.repo.head()]

    @property
    def index(self):
        return self.repo.open_index()

    @classmethod
    def init(cls, path):
        """Initialize a repository"""
        repo = DRepo.init(path)
        return cls(repo)

    @classmethod
    def init_bare(cls, path):
        repo = DRepo.init_bare(path)
        return cls(repo)

    def get_client(self, origin_uri=None, **kwargs):
        # Get the remote URL
        origin_uri = origin_uri or self.origin_uri

        # Fail if inexistant
        if not origin_uri:
            raise InvalidRemoteUrl()

        client_kwargs = {}
        auth_kwargs = self.authenticator.kwargs()

        client_kwargs.update(auth_kwargs)
        client_kwargs.update(kwargs)

        client, remote_path = get_transport_and_path(origin_uri, **client_kwargs)
        return client, remote_path

    def push_to(self, origin_uri, branch_name=None):
        selector = self._wants_branch(branch_name=branch_name)
        client, remote_path = self.get_client(origin_uri)
        return client.send_pack(remote_path, selector, self.repo.object_store.generate_pack_contents)

    # Like: git push
    def push(self, origin_uri=None, branch_name=None):
        return self.push_to(origin_uri, branch_name)

    def pull_from(self, origin_uri, branch_name=None):
        return self.fetch(origin_uri)

    # Like: git pull
    def pull(self, origin_uri=None, branch_name=None):
        return self.pull_from(origin_uri, branch_name)

    def fetch(self, origin_uri=None):
        # Get client
        client, remote_path = self.get_client(origin_uri=origin_uri)

        # Fetch data from remote repository
        remote_refs = client.fetch(remote_path, self.repo)

        # Update head
        self.repo["HEAD"] = remote_refs["HEAD"]

        # Rebuild index
        build_index_from_tree(self.repo.path, self.repo.index_path(),
                        self.repo.object_store, self.repo['HEAD'].tree)

        return self

    @classmethod
    def clone_remote(cls, origin_uri, local_path, auth=None, mkdir=True, **kwargs):
        """Clone a remote repository"""
        if mkdir and not(os.path.exists(local_path)):
            os.makedirs(local_path)

        # Initialize the local repository
        local_repo = DRepo.init(local_path)

        repo = cls(local_repo, origin_uri=origin_uri, auth=auth)

        repo.fetch()

        # Add origin
        # TODO

        return repo

    @classmethod
    def clone(cls):
        """Clone a local repository"""
        pass

    def _commit(self, commiter=None, author=None, message=None, *args, **kwargs):
        message = message or self.DEFAULT_MESSAGE
        return self.repo.do_commit(
            message=message,
            author=author,
            commmiter=commiter)

    # Like: git commmit -a
    def commit(self, name=None, email=None, message=None):
        user_info = {
            'name': name,
            'email': email,
        }
        return self._commit(
            commiter=user_info,
            author=user_info,
            message=message)

    # Commit only a set of files
    def commit_files(self, files, *args, **kwargs):
        pass

    @property
    @utils.transform(set)
    def tracked_files(self):
        return self.index._byname.keys()

    @property
    @utils.transform(set)
    def raw_files(self):
        return utils.subpaths(self.path)

    @property
    @utils.transform(set)
    def ignored_files(self):
        return utils.subpaths(self.path, filters=self.filters)

    @property
    @utils.transform(set)
    def trackable_files(self):
        return self.raw_files - self.ignored_files

    @property
    @utils.transform(set)
    def untracked_files(self):
        return self.trackable_files - self.tracked_files

    @property
    @utils.transform(set)
    def modified_staged_files(self):
        """Checks if the file has changed since last commit"""
        timestamp = self.last_commit.commit_time
        index = self.index
        return [
            f
            for f in self.tracked_files
            if index[f][1][0] > timestamp
        ]

    @property
    @utils.transform(set)
    def modified_unstaged_files(self):
        timestamp = self.last_commit.commit_time
        return [
            f
            for f in self.tracked_files
            if os.stat(self.abspath(f)).st_mtime > timestamp
        ]

    def _lookup_file(self, filename):
        return

    @property
    @utils.transform(set)
    def modified_files(self):
        return self.modified_staged_files | self.modified_unstaged_files

    # Like: git add
    @utils.arglist_method
    def add(self, files):
        return self.repo.stage(files)

    # Like: git rm
    @utils.arglist_method
    def rm(self, files, force=False):
        index = self.index
        index_files = filter(lambda f: f in index, files)
        for f in index_files:
            del self.index[f]
        return index.write()

    def mv_fs(self, file_pair):
        old_name, new_name = file_pair
        os.rename(old_name, new_name)

    # Like: git mv
    @utils.arglist_method
    def mv(self, files_pair):
        index = self.index
        files_in_index = filter(lambda f: f[0] in index, files_pair)
        map(self.mv_fs, files_in_index)
        old_files = map(utils.first, files_in_index)
        new_files = map(utils.last, files_in_index)
        self.add(new_files)
        self.rm(old_files)
        self.add(old_files)
        return

    @utils.arglist_method
    def checkout(self, files):
        pass

    @utils.arglist_method
    def reset(self, files, commit='HEAD'):
        pass

    def rm_all(self):
        self.index.clear()
        return self.index.write()
