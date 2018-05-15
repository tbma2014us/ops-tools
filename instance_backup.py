#!/usr/bin/env python
import Queue
import logging
import multiprocessing
import os
import signal
import sys
import threading
import time

import argparse
import boto3
import botocore.exceptions
import datetime

q = Queue.Queue()


# noinspection PyTypeChecker
class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'description',
            'Backs up EC2 instances into AMIs by tag or instance_id/name')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.formatter_class = argparse.RawTextHelpFormatter
        self.options = None
        self.epilog = '''
Configure your AWS access using: IAM, ~root/.aws/credentials, ~root/.aws/config, /etc/boto.cfg,
~root/.boto, or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
'''
        self.options = None
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
    logging.info('Started creating %s' % ami_name)
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
            botocore.exceptions.NoCredentialsError) as e:
        logging.error(e)
        return False, None


def clean_up(conn, instance, region):
    try:
        instance_name = get_tag(instance.tags, 'Name')
        filters = [{'Name': 'state', 'Values': ['available']},
                   {'Name': 'name', 'Values': ['%s_%s_*' % (
                       instance_name,
                       region
                   )]}]
        images = list(conn.images.filter(Filters=filters))
        logging.info('Found %s images for %s (%s) in %s' % (
            len(images),
            instance_name,
            instance.id,
            region
        ))
        current_week = datetime.datetime.utcnow().isocalendar()[1]
        purgeable = sorted(images, key=lambda x: x.creation_date, reverse=True)[7:]
        not_purgeable = get_all_used_amis(conn)
        for ami in purgeable:
            ami_creation_week = datetime.datetime.strptime(
                ami.creation_date, '%Y-%m-%dT%H:%M:%S.%fZ').isocalendar()[1]
            if ami_creation_week != current_week:
                not_purgeable.append(ami)
                current_week = ami_creation_week
            if len(not_purgeable) >= 7:
                break
        deleting = [ami for ami in purgeable if ami not in not_purgeable]
        if deleting:
            logging.info('De-registering %s images for %s' % (
                len(deleting),
                instance_name)
            )
            for ami in deleting:
                conn.meta.client.deregister_image(ImageId=ami.id)
                time.sleep(15)
    except (botocore.exceptions.ClientError,
            botocore.exceptions.NoCredentialsError) as e:
        logging.error(e)


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
    filters = filters or [dict(Name='tag:Name', Values=[host])]
    if host.startswith("i-") and (len(host) == 10 or len(host) == 19):
        instances = conn.instances.filter(InstanceIds=[host])
    else:
        instances = conn.instances.filter(
            Filters=filters
        )
    not list(instances) and logging.error('Cannot find %s' % host)
    return [i.id for i in instances]


def get_all_used_amis(conn):
    used_amis = []
    instances = list(conn.instances.filter())
    for instance in instances:
        if instance.image_id not in used_amis:
            used_amis.append(instance.image_id)
    return used_amis


def sigterm_handler(*args):
    logging.info("Exiting %s on signal %s" % (os.getpid(), args[0]))
    sys.exit(0)


def main(args=sys.argv[1:]):
    my_parser = ArgsParser()
    options = my_parser.parse_args(args)

    for m in ['boto3', 'botocore']:
        not options.verbose and logging.getLogger(m).setLevel(logging.CRITICAL)

    for s in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(s, sigterm_handler)

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
            instances = lookup(ec2, '', filters=[dict(Name='tag:Backup', Values=['yes'])])

        map(q.put, instances)
        for t in range(multiprocessing.cpu_count() * 2):
            worker_thread = threading.Thread(target=worker, args=[options.profile, options.region])
            worker_thread.daemon = True
            worker_thread.start()
            threads.append(worker_thread)

        while len(threading.enumerate()) > 1:
            if datetime.datetime.now() - start > datetime.timedelta(hours=2):
                raise SystemExit('Exiting on timeout')
            time.sleep(1)

    except (botocore.exceptions.ClientError,
            botocore.exceptions.NoCredentialsError) as e:
        raise SystemExit(e)


if __name__ == '__main__':
    main()
