from base64 import decodestring
from collections import defaultdict
from datetime import datetime
from fnmatch import fnmatch
from glob import glob
import io
from json import dumps
from os import chmod, unlink, symlink, makedirs
from os.path import join, dirname, basename, isdir, islink
import re
from shutil import copytree, rmtree
from tarfile import TarFile

from logging import basicConfig, getLogger, DEBUG, INFO
LOG_LEVEL = INFO
basicConfig(format = '%(asctime)s %(levelname)s: [%(funcName)s] %(message)s', datefmt = '%Y-%m-%d %H:%M:%S', level = LOG_LEVEL)
LOGGER = getLogger(__name__)

from sf import DEFAULT_ENCODING
from sf.solution import autodetect_solution, ExecutionException
from sf.testcases import TestCase, TestCases, DEFAULT_ENCODING

UID_TIMESTAMP_RE = re.compile( r'.*/(?P<uid>.+)/(?P<timestamp>[0-9]+)\.tar' )

def isots(timestamp):
    return datetime.fromtimestamp(int(timestamp)/1000).isoformat()

def json_dump(data, path):
    with io.open(path, 'w', encoding = DEFAULT_ENCODING) as f: f.write(dumps(data, ensure_ascii = False, sort_keys = True, indent = 4))

def rmrotree( path ):
	def _oe(f, p, e):
		if p == path: return
		pp = dirname(p)
		chmod(pp, 0700)
		chmod(p, 0700)
		unlink(p)
	rmtree(path, onerror = _oe)


class TristoMietitoreConfig(object):

    def __init__(self, path):
        config = {}
        with open(path, 'r') as f: exec f in config
        self.path = path
        self.tar_data = io.BytesIO(decodestring(config['TAR_DATA']))
        self.cached_cases = {}

    def cases(self, exercise):
        if exercise in self.cached_cases: return self.cached_cases[exercise]
        self.tar_data.seek(0)
        cases = {}
        with TarFile.open(mode = 'r', fileobj = self.tar_data ) as tf:
            for m in tf.getmembers():
                if m.isfile():
                    for kind in TestCase.KINDS:
                        if fnmatch(m.name, join(exercise, TestCase.GLOBS[kind])):
                            name = TestCase.TEST_NUM_RE.match(basename(m.name)).group(1)
                            data = tf.extractfile(m).read().decode(DEFAULT_ENCODING)
                            tc = cases.get(name, TestCase(name))
                            if kind == 'args': data = TestCase.u2args(data)
                            setattr(tc, kind, data)
                            cases[name] = tc
        tcs = TestCases(cases) if cases else None
        self.cached_cases[exercise] = tcs
        return tcs


class TristoMietitoreUploads(object):

    def __init__(self, path):
        if not isdir(path): raise IOError('{} is not a directory'.format(path))
        self.path = path
        uid2timestamps = defaultdict(list)
        for tf in glob(join(path, '*', '[0-9]*.tar')):
            m = UID_TIMESTAMP_RE.match(tf)
            if m:
                gd = m.groupdict()
                uid2timestamps[gd['uid']].append(gd['timestamp'])
        self.uid2timestamps = dict(uid2timestamps)

    def uids(self):
        return self.uid2timestamps.keys()

    def untar(self, uid, timestamp = None, clean = True):
        if timestamp is None: timestamp = max(self.uid2timestamps[uid])
        dest_dir = join(self.path, uid, timestamp)
    	if not clean and isdir(dest_dir):
            LOGGER.info( 'Upload for uid {} skipped ({})'.format(uid, isots(timestamp)))
            exercises = []
        else:
            rmrotree(dest_dir)
            makedirs(dest_dir, 0700) # to have a placemark in case of empty tars
            with TarFile.open(join(self.path, uid, timestamp + '.tar'), mode = 'r') as tf: tf.extractall(dest_dir)
    	    LOGGER.info( 'Upload for uid {} untarred ({})'.format(uid, isots(timestamp)))
            exercises = map(basename, filter(isdir, glob(join(dest_dir, '*'))))
        latest = join(self.path, uid, 'latest')
    	if islink(latest): unlink(latest)
    	symlink(timestamp, latest)
        return exercises

def tmtest(config, uploads, uid, timestamp = None, clean = True):
    exercises = uploads.untar(uid, timestamp, clean)
    for exercise in exercises:
        exercise_path = join(uploads.path, uid, 'latest', exercise)
        cases = config.cases(exercise)
        if cases is None:
            LOGGER.warn('Missing cases for: {}, in: {}'.format(exercise_path, config.path))
            continue
        compile_case = TestCase('<COMPILE>')
        solution = autodetect_solution(exercise_path)
        if solution is None:
            compile_case.errors = u'Missing (or ambiguous) solution'
            LOGGER.warn('Missing (or ambiguous) solution in {} for uid {}'.format(exercise, uid))
        else:
            compilation_result = solution.compile()
            if compilation_result.returncode:
                compile_case.errors = compilation_result.stderr.decode(DEFAULT_ENCODING)
                LOGGER.warn( 'Failed to compile exercise {} for uid {}'.format(exercise, uid))
        result = [compile_case.to_dict()]
        if not compile_case.errors:
            LOGGER.info( 'Compiled exercise {} for uid {}'.format(exercise, uid))
            num_cases = cases.fill_actual(solution)
            LOGGER.info( 'Run {} test cases for {} for uid {}'.format(num_cases, exercise, uid))
            cases.write(exercise_path)
            result.extend(cases.to_list_of_dicts())
        json_dump(result, join(uploads.path, uid, 'latest', 'TEST-{}.json'.format(exercise)))
