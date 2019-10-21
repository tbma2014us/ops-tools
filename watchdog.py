#!/usr/bin/env python
"""
    Monitors the availability of the TCP port, runs external process if port is unavailable,
    but not more frequently than cooldown timeout. Persistent information is stored in /tmp
"""
import argparse
import contextlib
import datetime
import logging.handlers
import os
import random
import shelve
import shlex
import socket
import subprocess
import sys
import tempfile
import time


logger = logging.getLogger()


# noinspection PyTypeChecker
class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'description',
            'Monitors the availability of the TCP port, runs external process if port is unavailable,\n'
            'but not more frequently than cooldown timeout.\n')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.formatter_class = argparse.RawTextHelpFormatter
        self.epilog = '''
For example:
    {} -a 192.168.1.1 -p 80 -c "restart service"
'''.format(__file__)
        self.options = None
        self.add_argument('-a', '--address', dest='service_address', default='192.168.1.230')
        self.add_argument('-p', '--port', dest='service_port', type=int, default=22)
        self.add_argument('-r', '--retry_after', type=int, dest='seconds', default=61)
        self.add_argument('-c', '--command', dest='command', default='echo restarting')
        self.add_argument('-cd', '--cooldown', type=int, dest='hours', default=4)

    def error(self, message):
        sys.stderr.write('error: %s\n' % message)
        self.print_help()
        sys.exit(2)

    def parse_args(self, *args, **kwargs):
        options = argparse.ArgumentParser.parse_args(self, *args, **kwargs)
        options.log_format = '%(filename)s:%(lineno)s[%(process)d]: %(levelname)s %(message)s'
        options.command_cooldown = datetime.timedelta(hours=options.hours)
        options.name = os.path.splitext(__file__)[0]
        self.options = options
        return options


def execute(command):
    try:
        exec_errors = subprocess.call(shlex.split(command))
        if not exec_errors:
            logging.info('Watchdog executed "%s"' % shlex.split(command))
            return datetime.datetime.now()
    except OSError as e:
        logging.error('Exec error: %s' % e)
        raise SystemExit(1)


def start_logging(_log_format):
    _logger = logging.getLogger()
    try:
        handler = logging.handlers.SysLogHandler(address='/dev/log')
    except socket.error:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_log_format))
    _logger.setLevel(logging.INFO)
    _logger.addHandler(handler)
    return _logger


def main(args=sys.argv[1:]):
    myparser = ArgsParser()
    options = myparser.parse_args(args)
    global logger
    logger = start_logging(options.log_format)

    try:
        logging.info('Starting watchdog run')
        with contextlib.closing(shelve.open(os.path.join(tempfile.gettempdir(), options.name), 'c')) as shelf, \
                contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(5)
            connect_errors = None
            executed = shelf.get(options.name)
            for _ in range(0, random.randint(3, 5)):
                connect_errors = sock.connect_ex(
                    (options.service_address, options.service_port))
                if not connect_errors:
                    break
                else:
                    logging.info('Trying to connect to %s:%s' % (
                        options.service_address, options.service_port))
                    time.sleep(options.seconds)
            else:
                logging.info('Cannot connect to %s:%s, issuing exec' %
                             (options.service_address, options.service_port))
            if connect_errors and not executed:
                shelf[options.name] = execute(options.command)
            elif connect_errors and executed:
                if datetime.datetime.now() - executed >= options.command_cooldown:
                    shelf[options.name] = execute(options.command)
                else:
                    next_run = (executed + options.command_cooldown).strftime('%Y-%m-%d %H:%M:%S')
                    logging.info('Watchdog exec cooldown is in effect until %s' % next_run)
            else:
                logging.info('%s:%s OK' % (options.service_address, options.service_port))
                shelf.clear()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
