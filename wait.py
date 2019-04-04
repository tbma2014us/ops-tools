#!/usr/bin/env python
import argparse
import errno
import logging
import socket
import sys
import time
import warnings

import cryptography.utils
import paramiko

# silence EllipticCurvePublicNumbers deprecation warnings
warnings.simplefilter("ignore", cryptography.utils.CryptographyDeprecationWarning)


# noinspection PyTypeChecker
class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('description', 'Wait for SSH service availability after a boot or reboot')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.formatter_class = argparse.RawTextHelpFormatter
        self.options = None
        self.epilog = '''
For example:
  {0} 192.168.1.1
  {0} 192.168.1.1 22 1 -t 80 -r 1
  {0} 192.168.1.1 22 1 --timeout 80 --retry-interval 1
'''.format(__file__)
        self.add_argument('host', help='remote hostname or IP address to connect')
        self.add_argument('port', help='SSH port', nargs="?", default="22")
        self.add_argument('-t', '--timeout', help='timeout in seconds', nargs="?", default="180")
        self.add_argument('-r', '--retry_interval', '--retry-interval', help='retry interval', nargs="?", default="1")

    def error(self, message):
        sys.stderr.write('Error: %s\n' % message)
        self.print_help()
        sys.exit(errno.EINVAL)

    def parse_args(self, *args, **kwargs):
        options = argparse.ArgumentParser.parse_args(self, *args, **kwargs)
        options.log_format = '%(asctime)s [%(levelname)s] (%(filename)s:%(threadName)s:%(lineno)s) %(message)s'
        self.options = options
        return options


def wait_for_ssh_to_be_ready(host, port, timeout, retry_interval):
    client = paramiko.client.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    timeout_start = time.time()
    while time.time() < timeout_start + int(timeout):
        try:
            time.sleep(float(retry_interval))
            client.connect(
                host,
                int(port),
                allow_agent=False,
                look_for_keys=False,
                timeout=1
            )
        except paramiko.ssh_exception.SSHException as _:
            if _.message == 'Error reading SSH protocol banner':
                logging.info(_)
                continue
            logging.info('SSH transport is available!')
            break
        except paramiko.ssh_exception.NoValidConnectionsError as _:
            logging.info('SSH transport is not ready')
            continue
        except socket.error as _:
            logging.info(str(_).capitalize())
            continue
        except KeyboardInterrupt:
            sys.exit(errno.EINTR)
    else:
        logging.critical("Timeout exceeded")
        sys.exit(errno.ETIME)


def main(args=sys.argv[1:]):
    my_parser = ArgsParser()
    options = my_parser.parse_args(args)
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format=options.log_format
    )
    wait_for_ssh_to_be_ready(
        options.host,
        options.port,
        options.timeout,
        options.retry_interval
    )


if __name__ == '__main__':
    main()
