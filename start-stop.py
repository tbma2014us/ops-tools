#!/usr/bin/env python
import logging
import sys

import argparse
import boto3
import botocore.exceptions

LOG_FORMAT = '%(asctime)s %(filename)s:%(lineno)s[%(process)d]: %(levelname)s: %(message)s'


class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'description',
            'Starts or stops ec2 instances by name or id')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.formatter_class = argparse.RawTextHelpFormatter
        self.options = None
        self.epilog = '''
For example
    {} stop name1 name2 name3
'''.format(__file__)
        self.add_argument('-r', '--regions', dest='region', default='us-west-2', help='Region to connect')
        self.add_argument('-p', '--profile', dest='profile', help='Profile to use')
        self.add_argument('--dry-run', '--dry_run', dest='dry_run', action='store_true', default=False,
                          help="Don't actually do anything; just print out what would be done")
        self.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Be verbose')
        self.add_argument('command', choices=('start', 'stop'))
        self.add_argument('name', help="Names or id's of the EC2 instances", nargs='+')

    def error(self, message):
        sys.stderr.write('ERROR: %s\n\n' % message)
        self.print_help()
        sys.exit(2)

    def parse_args(self, *args, **kwargs):
        options = argparse.ArgumentParser.parse_args(self, *args, **kwargs)
        self.options = options
        return options


def lookup(conn, host):
    if host.startswith("i-") and (len(host) == 10 or len(host) == 19):
        instances = conn.instances.filter(InstanceIds=[host])
    else:
        instances = conn.instances.filter(
            Filters=[dict(Name='tag:Name', Values=[host])]
        )
    not list(instances) and logging.error('Cannot find %s' % host)
    return [i.id for i in instances]


def main():
    my_parser = ArgsParser()
    options = my_parser.parse_args(sys.argv[1:])
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=LOG_FORMAT)

    for m in ['boto3', 'botocore']:
        not options.verbose and logging.getLogger(m).setLevel(logging.CRITICAL)

    try:
        session = boto3.session.Session(region_name=options.region, profile_name=options.profile)
        ec2 = session.resource('ec2')
        instances = []

        for name in options.name:
            instances.extend(
                lookup(ec2, name)
            )

        if instances:
            if options.command == 'start':
                session.client('ec2').start_instances(
                    InstanceIds=instances,
                    DryRun=options.dry_run
                )
            elif options.command == 'stop':
                session.client('ec2').stop_instances(
                    InstanceIds=instances,
                    DryRun=options.dry_run
                )

    except (botocore.exceptions.ClientError,
            botocore.exceptions.NoCredentialsError) as e:
        raise SystemExit(e)


if __name__ == '__main__':
    main()
