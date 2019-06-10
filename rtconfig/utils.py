# -*- coding: utf-8 -*-
import io
import os
import json
import zipfile
import contextlib
import tempfile
import shutil
import sys
import tarfile
import mimetypes
import subprocess
import click
import hashlib
import time
import datetime
from functools import partial
from collections import defaultdict


class AbortedError(Exception):
    pass


def get_content_type(name):
    return mimetypes.guess_type(name)[0] or "string"


def serialize_to_json(data):
    return json.dumps(data, indent=2, separators=(',', ': ')) + '\n'


class ImportStringError(ImportError):

    """Provides information about a failed :func:`import_string` attempt."""

    #: String in dotted notation that failed to be imported.
    import_name = None
    #: Wrapped exception.
    exception = None

    def __init__(self, import_name, exception):
        self.import_name = import_name
        self.exception = exception

        msg = (
            'import_string() failed for %r. Possible reasons are:\n\n'
            '- missing __init__.py in a package;\n'
            '- package or module path not included in sys.path;\n'
            '- duplicated package or module name taking precedence in '
            'sys.path;\n'
            '- missing module, class, function or variable;\n\n'
            'Debugged import:\n\n%s\n\n'
            'Original exception:\n\n%s: %s')

        name = ''
        tracked = []
        for part in import_name.replace(':', '.').split('.'):
            name += (name and '.') + part
            imported = import_string(name, silent=True)
            if imported:
                tracked.append((name, getattr(imported, '__file__', None)))
            else:
                track = ['- %r found in %r.' % (n, i) for n, i in tracked]
                track.append('- %r not found.' % name)
                msg = msg % (import_name, '\n'.join(track),
                             exception.__class__.__name__, str(exception))
                break

        ImportError.__init__(self, msg)

    def __repr__(self):
        return '<%s(%r, %r)>' % (self.__class__.__name__, self.import_name,
                                 self.exception)


def import_string(import_name, silent=False):
    import_name = str(import_name).replace(':', '.')
    try:
        try:
            __import__(import_name)
        except ImportError:
            if '.' not in import_name:
                raise
        else:
            return sys.modules[import_name]

        module_name, obj_name = import_name.rsplit('.', 1)
        try:
            module = __import__(module_name, None, None, [obj_name])
        except ImportError:
            # support importing modules not yet set up by the parent module
            # (or package for that matter)
            module = import_string(module_name)

        try:
            return getattr(module, obj_name)
        except AttributeError as e:
            raise ImportError(e)

    except ImportError as ex:
        if not silent:
            raise(
                ImportStringError,
                ImportStringError(import_name, ex),
                sys.exc_info()[2])


class OSUtils(object):
    ZIP_DEFLATED = zipfile.ZIP_DEFLATED

    def environ(self):
        return os.environ

    def open(self, filename, mode):
        return open(filename, mode)

    def open_zip(self, filename, mode, compression=ZIP_DEFLATED):
        return zipfile.ZipFile(filename, mode, compression=compression)

    def remove_file(self, filename):
        """Remove a file, noop if file does not exist."""
        # Unlike os.remove, if the file does not exist,
        # then this method does nothing.
        try:
            os.remove(filename)
        except OSError:
            pass

    def file_exists(self, filename):
        return os.path.isfile(filename)

    def get_file_contents(self, filename, binary=True, encoding='utf-8'):
        # It looks like the type definition for io.open is wrong.
        # the encoding arg is unicode, but the actual type is
        if binary:
            mode = 'rb'
            # In binary mode the encoding is not used and most be None.
            encoding = None
        else:
            mode = 'r'
        with io.open(filename, mode, encoding=encoding) as f:
            return f.read()

    def set_file_contents(self, filename, contents, binary=True):
        if binary:
            mode = 'wb'
        else:
            mode = 'w'
        with open(filename, mode) as f:
            f.write(contents)

    def extract_zipfile(self, zipfile_path, unpack_dir):
        with zipfile.ZipFile(zipfile_path, 'r') as z:
            z.extractall(unpack_dir)

    def extract_tarfile(self, tarfile_path, unpack_dir):
        with tarfile.open(tarfile_path, 'r:*') as tar:
            tar.extractall(unpack_dir)

    def directory_exists(self, path):
        return os.path.isdir(path)

    def get_directory_contents(self, path):
        return os.listdir(path)

    def makedirs(self, path):
        os.makedirs(path)

    def dirname(self, path):
        return os.path.dirname(path)

    def abspath(self, path):
        return os.path.abspath(path)

    def joinpath(self, *args):
        return os.path.join(*args)

    def walk(self, path):
        return os.walk(path)

    def copytree(self, source, destination):
        if not os.path.exists(destination):
            self.makedirs(destination)
        names = self.get_directory_contents(source)
        for name in names:
            new_source = os.path.join(source, name)
            new_destination = os.path.join(destination, name)
            if os.path.isdir(new_source):
                self.copytree(new_source, new_destination)
            else:
                shutil.copy2(new_source, new_destination)

    def rmtree(self, directory):
        shutil.rmtree(directory)

    def copy(self, source, destination):
        shutil.copy(source, destination)

    def move(self, source, destination):
        shutil.move(source, destination)

    def md5_file(self, file_name):
        with open(file_name, mode='rb') as f:
            d = hashlib.md5()
            for buf in iter(partial(f.read, 128), b''):
                d.update(buf)
        return d.hexdigest()

    @contextlib.contextmanager
    def tempdir(self):
        tempdir = tempfile.mkdtemp()
        try:
            yield tempdir
        finally:
            shutil.rmtree(tempdir)

    def popen(self, command, stdout=None, stderr=None, env=None):
        p = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env)
        return p

    def mtime(self, path):
        return os.stat(path).st_mtime

    @property
    def pipe(self):
        return subprocess.PIPE

    def recreate_dir(self, directory):
        if self.directory_exists(directory):
            self.rmtree(directory)
        self.makedirs(directory)


class UI(object):
    def __init__(self, out=None, err=None, confirm=None):
        # I tried using a more exact type for the 'confirm'
        # param, but mypy seems to miss the 'if confirm is None'
        # check and types _confirm as Union[..., None].
        # So for now, we're using Any for this type.
        if out is None:
            out = sys.stdout
        if err is None:
            err = sys.stderr
        if confirm is None:
            confirm = click.confirm
        self._out = out
        self._err = err
        self._confirm = confirm

    def write(self, msg):
        self._out.write(msg)

    def error(self, msg):
        self._err.write(msg)

    def confirm(self, msg, default=False, abort=False):
        try:
            return self._confirm(msg, default, abort)
        except click.Abort:
            raise AbortedError()


def object_merge(old, new, unique=False):
    if isinstance(old, list) and isinstance(new, list):
        if old == new:
            return
        for item in old[::-1]:
            if unique and item in new:
                continue
            new.insert(0, item)
    if isinstance(old, dict) and isinstance(new, dict):
        for key, value in old.items():
            if key not in new:
                new[key] = value
            else:
                object_merge(value, new[key])


def freeze(o):
    if isinstance(o, dict):
        return tuple(sorted([(k, freeze(v)) for k, v in o.items()],
                              key=lambda x: x[0]))
    elif isinstance(o, list):
        return tuple([freeze(v) for v in o])
    elif isinstance(o, tuple):
        return tuple([freeze(v) for v in o])
    elif isinstance(o, set):
        return tuple([freeze(v) for v in sorted(o)])
    return o


def to_hash(*sub, **kw):
    content = str(freeze([sub, kw])).encode('utf-8', 'ignore')
    return hashlib.md5(content).hexdigest()[8:-8]


def strptime(str_dtime, time_format='%Y-%m-%d %H:%M:%S'):
    '''
    字符串转化为 datetime for < 2.6
    @str_dtime: 字符串格式的时间
    @time_format: 时间格式串
    return: datetime.datetime
    '''
    time_stamp = time.mktime(time.strptime(str_dtime, time_format))
    return datetime.datetime.fromtimestamp(time_stamp)


def strftime(date_time, time_format='%Y-%m-%d %H:%M:%S'):
    """
    格式化时间
    @date_time: 时间对象
    @time_format: 时间格式串
    return: 字符串时间
    """
    return datetime.datetime.strftime(date_time, time_format)


def convert_dt(value):
    if not value:
        value = datetime.datetime.now()
    if isinstance(value, str):
        value = strptime(value)
    if not isinstance(value, datetime.datetime):
        raise TypeError
    return value


def format_env_data(env_data, **variable):

    def _convert(data):
        if isinstance(data, dict):
            for key, value in data.items():
                data[key] = _convert(value)
        elif isinstance(data, list):
            for idx, value in enumerate(data):
                data[idx] = _convert(value)
        elif isinstance(data, str):
            data = data.format_map(defaultdict(str, **variable))
        return data
    return _convert(env_data)
