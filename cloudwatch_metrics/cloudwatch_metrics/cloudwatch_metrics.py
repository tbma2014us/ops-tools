import datetime
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pprint import pformat

import argparse
import boto3
import botocore.client
import botocore.exceptions
import requests

__version__ = '1.0.0'
logger = logging.getLogger()


class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'description',
            'Runs as a service. Every 5 minutes puts custom metrics into CloudWatch')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.formatter_class = argparse.ArgumentDefaultsHelpFormatter
        self.epilog = '''
            Configure your AWS access using: IAM, ~root/.aws/credentials, ~root/.aws/config, /etc/boto.cfg,
             ~root/.boto, or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
            '''
        self.options = None
        self.add_argument('-p', '--profile', dest='profile', help='AWS profile to use')
        self.add_argument('-r', '--region', dest='region', default='us-west-2', help='AWS region to connect')
        self.add_argument('-i', '--interval', dest='interval', type=int, default=5, help='Sleep for that many minutes')
        self.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Be verbose')

    def error(self, message):
        sys.stderr.write('Error: %s\n' % message)
        self.print_help()
        sys.exit(2)

    def parse_args(self, *args, **kwargs):
        options = argparse.ArgumentParser.parse_args(self, *args, **kwargs)
        options.log_format = '%(filename)s:%(lineno)s[%(process)d]: %(levelname)s %(message)s'
        options.name = os.path.basename(__file__)
        options.interval *= 60
        self.options = options
        return options


def pick(iterable, _g, *_args):
    vs = list(_args)
    for i, arg in enumerate(_args):
        for item in iterable:
            v = _g(item, arg)
            if v:
                vs[i] = v
                break
    return vs


def collect_metrics():
    data = list()

    def collect(f):
        name = f.__name__.title().replace('_', '')
        for value in f():
            data.append((name, value))

    @collect
    def memory_utilization():
        with open('/proc/meminfo') as f:
            def match(line, item):
                meminfo_regex = re.compile(r'([A-Z][A-Za-z()_]+):\s+(\d+)(?: ([km]B))')
                name, amount, unit = meminfo_regex.match(line).groups()
                if name == item:
                    assert unit == 'kB'
                    return int(amount)
            memtotal, memfree, buffers, _cached = pick(
                f, match, 'MemTotal', 'MemFree', 'Buffers', 'Cached'
            )
            inactive = (memfree + buffers + _cached) / float(memtotal)
            yield round(100 * (1 - inactive), 1), "Percent", ()

    @collect
    def disk_space_utilization():
        with open('/proc/mounts') as f:
            for line in f:
                if not line.startswith('/'):
                    continue
                device, _path, filesystem, options = line.split(' ', 3)
                result = os.statvfs(_path)
                if not result.f_blocks:
                    continue
                free = result.f_bfree / float(result.f_blocks)
                yield round(100 * (1 - free), 1), "Percent", (
                    ("Filesystem", device),
                    ("MountPath", _path)
                )

    @collect
    def load_average():
        with open('/proc/loadavg') as f:
            line = f.read()
            load = float(line.split(' ', 1)[0])
            yield round(load, 2), "Count", ()

    @collect
    def network_connections():
        i = 0
        with open('/proc/net/tcp') as f:
            for i, line in enumerate(f):
                pass
        yield i, "Count", (("Protocol", "TCP"), )
        with open('/proc/net/udp') as f:
            for i, line in enumerate(f):
                pass
        yield i, "Count", (("Protocol", "UDP"), )

    @collect
    def open_file_descriptor_count():
        p = subprocess.Popen(['lsof'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        t = threading.Timer(30, p.kill)
        try:
            t.start()
            c = p.stdout.read().count('\n')
            exit_code = p.wait()
        finally:
            t.cancel()
        if exit_code == 0:
            yield int(c), "Count", ()
        else:
            yield 0, "Count", ()

    return data


def metrics(_options):
    session = boto3.session.Session(
        profile_name=_options.profile or None, region_name=_options.region)
    data = collect_metrics()
    try:
        dimensions = ('InstanceId',
                      requests.get('http://169.254.169.254/latest/meta-data/instance-id', timeout=3).text
                      ),
    except requests.exceptions.ConnectionError:
        raise SystemExit('Fatal Error: Not running on AWS EC2 instance')
    for dimension in dimensions:
        _options.verbose and logging.info('Collected metrics:\n' + pformat(data))
        submit_metrics(session, _options.verbose, data, "System/Linux", dimension)
        logger.info(
            'Submitted %d metrics for dimension System/Linux: %s' % (len(data), dimension[0])
        )


def submit_metrics(_session, verbose, data, namespace,  *dimensions):
    config = botocore.client.Config(connect_timeout=5, retries={'max_attempts': 0})
    metric_data = list()
    for name, (value, unit, metric_dimensions) in data:
        metric_dimensions = tuple(metric_dimensions)
        _dimensions = list()
        for j, (_name, _value) in enumerate(dimensions + metric_dimensions):
            _dimensions.append(
                {
                    'Name': _name,
                    'Value': _value
                }
            )
        metric_data.append(
            {
                'MetricName': name,
                'Dimensions': _dimensions,
                'Value': value,
                'Unit': unit,
            }
        )
    verbose and logging.info('Submitting metrics:\n' + pformat(metric_data))
    try:
        _session.client('cloudwatch', config=config).put_metric_data(
            Namespace=namespace,
            MetricData=metric_data
        )
    except botocore.exceptions.ClientError as e:
        logging.error(e)


def sigterm_handler(*args):
    logging.info("Exiting {} on signal {}".format(os.getpid(), args[0]))
    sys.exit(0)


def main(args=sys.argv[1:]):
    signal.signal(signal.SIGINT, sigterm_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)
    logging.getLogger('botocore').setLevel(logging.CRITICAL)
    logging.getLogger('boto3').setLevel(logging.CRITICAL)

    my_parser = ArgsParser()
    options = my_parser.parse_args(args)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=options.log_format)
    logging.info('Starting %s' % options.name)

    while True:
        goal = datetime.datetime.now() + datetime.timedelta(seconds=options.interval)
        goal.replace(second=0, microsecond=0)
        metrics(options)
        dt = goal - datetime.datetime.now()
        sleep_time = dt.seconds + dt.microseconds / 10e6 if not dt.days < 0 else options.interval
        options.verbose and logging.info('Sleeping for %s seconds' % sleep_time)
        time.sleep(sleep_time)


if __name__ == '__main__':
    main()
