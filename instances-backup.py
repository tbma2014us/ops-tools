#!/usr/bin/env python3
import argparse
import datetime
import logging
import os
import signal
import sys
import threading
import time

import boto3
import botocore.exceptions

try:
    import Queue as queue
except ImportError:
    import queue

q = queue.Queue()


# noinspection PyTypeChecker
class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('description', 'Backs up EC2 instances into AMIs by tag or instance_id/name')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.formatter_class = argparse.RawTextHelpFormatter
        self.options = None
        self.epilog = '''
Configure your AWS access using: IAM, ~root/.aws/credentials, ~root/.aws/config, /etc/boto.cfg,
~root/.boto, or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.

By default searches and backs-up EC2 instances with Backup=yes tag.

For example:
    {0} -i myinstance1,myinstance2,myinstance3
'''.format(__file__)
        self.add_argument('-i', '--instances', dest='instances', help='EC2 instances to backup')
        self.add_argument('-p', '--profile', dest='profile', help='AWS profile to use')
        self.add_argument('-r', '--region', dest='region', default='us-west-2', help='AWS region to connect')
        self.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Be verbose')

    def error(self, message):
        sys.stderr.write('Error: %s\n' % message)
        self.print_help()
        sys.exit(2)

    def parse_args(self, *args, **kwargs):
        options = argparse.ArgumentParser.parse_args(self, *args, **kwargs)
        options.log_format = '[%(levelname)s] (%(filename)s:%(threadName)s:%(lineno)s) %(message)s'
        options.instances = options.instances.split(',') if options.instances else None
        options.name = os.path.abspath(os.path.dirname(__file__))
        self.options = options
        return options


def create_ami(conn, instance_id, ami_name, start, ami_desc=None):
    logging.info('Started creating image %s' % ami_name)
    try:
        request = conn.meta.client.create_image(
            Description=ami_desc or '',
            InstanceId=instance_id,
            Name=ami_name,
            NoReboot=True
        )
        image = conn.Image(request.get('ImageId'))

        while image.state == 'pending':
            logging.info('%s is %s for %s' % (
                ami_name,
                image.state,
                chop_microseconds(datetime.datetime.now() - start))
            )
            time.sleep(15)
            image.reload()

        if image.state == 'available':
            logging.info('Finished creating %s in %s' % (
                ami_name,
                chop_microseconds(datetime.datetime.now() - start))
            )
            return True, image.image_id
        else:
            return False, image.image_id

    except (botocore.exceptions.ClientError,
            botocore.exceptions.NoCredentialsError) as _:
        logging.error(_)
        return False, None


def clean_up(conn, instance, region):
    try:
        instance_name = get_tag(instance.tags, 'Name')
        images = list(conn.images.filter(Filters=[
            {'Name': 'state', 'Values': ['available']},
            {'Name': 'name', 'Values': ['%s_%s_*' % (instance_name, region)]}
        ]))
        logging.info('Found %s images for %s (%s) in %s' % (
            len(images),
            instance_name,
            instance.id,
            region
        ))

        current_week = datetime.datetime.utcnow().isocalendar()[1]
        purgeable = sorted(images, key=lambda x: x.creation_date, reverse=True)[7:]
        used_amis = get_all_used_amis(conn)
        not_purgeable = []

        for ami in purgeable:
            ami_creation_week = datetime.datetime.strptime(
                ami.creation_date, '%Y-%m-%dT%H:%M:%S.%fZ').isocalendar()[1]
            if ami_creation_week != current_week:
                not_purgeable.append(ami)
                current_week = ami_creation_week
            if len(not_purgeable) >= 7:
                break

        deleting = list(set(purgeable) - set(not_purgeable) - set(used_amis))
        if deleting:
            logging.info('De-registering %s image%s for %s' % (
                len(deleting),
                's' if len(deleting) > 1 else '',
                instance_name)
            )
            for ami in deleting:
                logging.info('De-registering %s (%s)' % (ami.name, ami.id))
                conn.meta.client.deregister_image(ImageId=ami.id)
                time.sleep(15)

    except (botocore.exceptions.ClientError,
            botocore.exceptions.NoCredentialsError) as _:
        logging.error(_)


def worker(profile, region):
    session = boto3.session.Session(profile_name=profile, region_name=region)
    while not q.empty():
        instance_id = q.get()
        now = datetime.datetime.now()
        instance = session.resource('ec2').Instance(instance_id)
        ami_name = '%s_%s_%s' % (
            get_tag(instance.tags, 'Name'),
            session.region_name,
            '%s%02d%02d.%02d%02d' % (
                now.year,
                now.month,
                now.day,
                now.hour,
                now.minute,
            ),
        )
        success, image_id = create_ami(session.resource('ec2'), instance.id, ami_name, now)
        if success and image_id:
            clean_up(session.resource('ec2'), instance, session.region_name)
        q.task_done()


def chop_microseconds(delta):
    return delta - datetime.timedelta(microseconds=delta.microseconds)


def get_tag(_tags, tag_name):
    tag = [tag['Value'] for tag in _tags if tag['Key'] == tag_name]
    return tag[0] if tag else 'Unknown'


def lookup(conn, host, filters=None):
    filters = filters or [{'Name': 'tag:Name', 'Values': [host]}]
    if host.startswith("i-") and (len(host) == 10 or len(host) == 19):
        instances = conn.instances.filter(InstanceIds=[host])
    else:
        instances = conn.instances.filter(
            Filters=filters
        )
    not list(instances) and logging.error('Cannot find %s' % host)
    return [i.id for i in instances]


def get_all_used_amis(conn):
    used_amis = [instance.image_id for instance in list(conn.instances.filter())]
    return list(set(used_amis))


def sigterm_handler(*args):
    sig_name = next(v for v, k in signal.__dict__.items() if k == args[0])
    logging.info('Exiting %s on %s' % (os.getpid(), sig_name))
    sys.exit(0)


def main(args=sys.argv[1:]):
    my_parser = ArgsParser()
    options = my_parser.parse_args(args)

    for _ in ['boto3', 'botocore']:
        not options.verbose and logging.getLogger(_).setLevel(logging.CRITICAL)

    for _ in [signal.SIGINT, signal.SIGTERM]:
        # noinspection PyTypeChecker
        signal.signal(_, sigterm_handler)

    try:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=options.log_format)
        session = boto3.session.Session(profile_name=options.profile, region_name=options.region)
        instances = []
        threads = []
        start = datetime.datetime.now()

        ec2 = session.resource('ec2', region_name=options.region)
        if options.instances:
            for instance in options.instances:
                instances.extend(lookup(ec2, instance))
        else:
            instances = lookup(ec2, '', filters=[{'Name': 'tag:Backup', 'Values': ['yes']}])

        map(q.put, instances)
        for _ in range(4):
            worker_thread = threading.Thread(target=worker, args=[options.profile, options.region])
            worker_thread.daemon = True
            worker_thread.start()
            threads.append(worker_thread)

        while len(threading.enumerate()) > 1:
            if datetime.datetime.now() - start > datetime.timedelta(hours=4):
                raise SystemExit('Exiting on timeout')
            time.sleep(1)

    except (botocore.exceptions.ClientError,
            botocore.exceptions.NoCredentialsError) as _:
        raise SystemExit(_)


if __name__ == '__main__':
    main()
