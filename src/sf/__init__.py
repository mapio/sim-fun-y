DEFAULT_ENCODING = 'utf-8'
MAX_BYTES_READ = 1048576
TEST_TIMEOUT = 1
VERSION = '0.1.24'

class WronglyEncodedFile(UnicodeError):
    pass
