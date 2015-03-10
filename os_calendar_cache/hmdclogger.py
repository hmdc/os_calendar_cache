#!/usr/bin/env python

__author__ = "Harvard-MIT Data Center DevOps"
__copyright__ = "Copyright 2014, HMDC"
__credits__ = ["Bradley Frank"]
__license__ = "GPL"
__maintainer__ = "HMDC"
__email__ = "linux@lists.hmdc.harvard.edu"
__status__ = "Production"

import inspect
import logging
import os
import sys


class HMDCLogger:
    """Module for standarizing HMDC python script logging. See the following:
        * https://docs.python.org/2/howto/logging-cookbook.html
        * https://docs.python.org/2/library/logging.html

    Example:
        # Create logger object at DEBUG level.
        hmdclog = HMDCLogger('MyLogger', 'DEBUG')
        # Enable logging to console.
        hmdclog.log_to_console()
        # Enable logging to file.
        hmdclog.log_to_file('/path/to/file', 'logFile.txt')

    Class Variables:
        DEF_LOG_FORMAT (string): The default display format of the logs.
        DEF_DATE_FORMAT (string): The default timestamp format of the logs.

    Public Functions:
        get_level: Returns the debugging level of the logger.
        log: Commits a message to the logger.
        log_to_console: Enables logging to the console.
        log_to_file: Enables logging to a file.
    """

    #
    # The format is a selection of attributes to display:
    #   https://docs.python.org/2/library/logging.html#logrecord-attributes
    # NOTE: Including "funcName" will not work because this is a wrapper.
    #
    DEF_LOG_FORMAT = "[%(asctime)s] [%(process)d] [%(levelname)8s] %(message)s"
    DEF_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, name, debug_level, log_format=None, date_format=None):
        """Creates an instance of HMDCLogger.

        Arguments:
            name (string): The name of the logger instance.
            debug_level (string): Amount of debug information to log.
            log_format (string): Output format of the log message.
            date_format (string): Format of the log timestamp.

        Attributes:
            debug_num (int): The logging level in numeric format.
            debug_str (string): The logging level in name format.
            logger (Logger): Instance of Logger class.
        """

        if log_format is None:
            log_format = self.DEF_LOG_FORMAT

        if date_format is None:
            date_format = self.DEF_DATE_FORMAT

        self.logger = logging.getLogger(name)
        self.log_format = logging.Formatter(log_format, date_format)

        # Python 2.6 requires the numeric value, not a string.
        self.debug_str = debug_level.upper()
        self.debug_num = logging.getLevelName(self.debug_str)
        if type(self.debug_num) is not int:
            raise TypeError("Debugging level was not recognized.")
        else:
            self.logger.setLevel(self.debug_num)

    def get_level(self, as_int=False):
        """Returns the debugging level of the logger."""
        if as_int:
            return self.debug_num
        else:
            return self.debug_str

    def log(self, level, message):
        """Handles the actual logging of messages.

        Arguments:
            level (string): Name of the logging level to use.
            message (string): The message to log.

        Attributes:
            level (int): Integer equivalent of the logging level.
            function (string): Name of the function making the log.
            filename (string): Filename of the calling function.
            source (string): Full source of call.
            log (string): Formatted message text with accompanying source.
        """

        level = logging.getLevelName(level.upper())

        if type(level) is not int:
            raise TypeError("Could not identify logging type for message \"" +
                            message + "\"")
        else:
            # The calling function is saved in the Python stack.
            function = inspect.stack()[1][3]

            #
            # The filename needs to be cleaned up by removing the leading path
            # and the file extension (which should always be ".py").
            #
            filename = inspect.stack()[1][1]
            filename = os.path.basename(filename)
            filename = os.path.splitext(filename)[0]

            source = filename + "." + function
            # Message is right-justified in a 35 character column.
            log = "{0:>35}: {1}".format(source, message)
            self.logger.log(level, log)

    def log_to_console(self):
        """Adds a console handler to the logger."""
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(self.debug_num)
        ch.setFormatter(self.log_format)
        self.logger.addHandler(ch)

    def log_to_file(self, log_file):
        """Adds a file handler to the logger."""
        fh = logging.FileHandler(log_file)
        fh.setLevel(self.debug_num)
        fh.setFormatter(self.log_format)
        self.logger.addHandler(fh)


if __name__ == '__main__':
    pass
