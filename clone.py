#!/usr/bin/env python3
import argparse
import datetime
import logging
import os
import pathlib
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import boto3
import botocore.exceptions

USER_DATA = '''#!/bin/bash
set -euxo pipefail
# docker does not survive network changes
rm -rf /var/lib/docker/network/
'''


class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('description', '''
Creates a copy of the running AWS instance''')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.options = None
        self.formatter_class = argparse.RawTextHelpFormatter
        self.epilog = '''
Configure your AWS access using: IAM, ~root/.aws/credentials, ~root/.aws/config, /etc/boto.cfg,
~root/.boto, or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.

Example usage: 
    %s --region us-east-1 myinstance''' % __file__
        self.add_argument('-p', '--profile', dest='profile', help='AWS profile to use')
        self.add_argument(
            '-r', '--region', dest='region', help='AWS region to connect', required=True)
        self.add_argument('name', help='Name of the EC2 or RDS instance')
        self.add_argument('--new-name', '--new_name', dest='new_name', help='Give clone that name')
        self.add_argument('--instance-type', '--instance_type', dest='instance_type', help='Instance Type'),
        self.add_argument('--image-id', '--image_id', dest='image_id', help='Image Id to use instead of the latest'),
        self.add_argument('--key-name', '--key_name', dest='key_name', help='Key name')
        self.add_argument(
            '--security-group-ids', '--security_group_ids', dest='security_group_ids', help='Security group ids')
        self.add_argument('--subnet-id', '--subnet_id', dest='subnet_id', help='Subnet id')
        self.add_argument('--user-data', '--user_data', dest='user_data', help='Userdata script file')
        self.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help="Be verbose")
        self.add_argument('--dry_run', '--dry-run', dest='dry_run', action='store_true', default=False,
                          help="Don't actually do anything; just print out what would be done")

    def error(self, message):
        sys.stderr.write('Error: %s\n' % message)
        self.print_help()
        exit(2)

    def parse_args(self, *args, **kwargs):
        options = argparse.ArgumentParser.parse_args(self, *args, **kwargs)
        options.log_format = '[%(levelname)s] (%(filename)s:%(threadName)s:%(lineno)s) %(message)s'
        if options.security_group_ids:
            if ',' in options.security_group_ids:
                options.security_group_ids = options.security_group_ids.split(',')
            else:
                options.security_group_ids = [options.security_group_ids]
        if options.user_data:
            _ = pathlib.Path(options.user_data)
            if not _.exists():
                sys.stderr.write('Error: "%s" does not exist\n' % _.resolve())
                exit(2)
            options.user_data = _.read_text()
        self.options = options
        return options


class Clone(object):
    def __init__(self, options):
        self.options = options
        self.session = boto3.session.Session(profile_name=options.profile, region_name=options.region)
        self.ec2_res = self.session.resource('ec2')
        self.ec2 = self.session.client('ec2')
        self.rds = self.session.client('rds')

    def ec2_lookup(self, host):
        try:
            if host.startswith("i-") and (len(host) == 10 or len(host) == 19):
                instances = self.ec2_res.instances.filter(InstanceIds=[host])
            else:
                instances = self.ec2_res.instances.filter(
                    Filters=[
                        {'Name': 'tag:Name', 'Values': [host]},
                        {'Name': 'instance-state-name', 'Values': ['running']}
                    ]
                )
            return str([i.id for i in instances][0])
        except (botocore.exceptions.ClientError, IndexError):
            return

    def rds_lookup(self, host):
        try:
            databases = self.rds.describe_db_instances(DBInstanceIdentifier=host)
            return databases.get('DBInstances')[0]
        except (botocore.exceptions.ClientError, IndexError):
            return

    def find_latest_ec2_snapshot(self, name):
        try:
            images = self.ec2.describe_images(Filters=[
                {'Name': 'name', 'Values': ['%s_%s_*' % (name, self.session.region_name)]},
                {'Name': 'state', 'Values': ['available']},
            ])['Images']
        except (botocore.exceptions.ClientError, IndexError):
            logging.error('Cannot find image for %s' % name)
            return
        if images:
            _sorted = sorted(images, key=lambda x: x['CreationDate'], reverse=False)
            _latest_date = datetime.strptime(_sorted[-1]['CreationDate'], '%Y-%m-%dT%H:%M:%S.%fZ')
            logging.info(
                'Latest "%s" snapshot (%s) is taken at %s' % (
                    name,
                    _sorted[-1].get('ImageId'),
                    _latest_date,
                )
            )
            return _latest_date, _sorted[-1]
        else:
            return None, None

    def find_latest_rds_snapshot(self, name):
        images = self.rds.describe_db_snapshots(
            DBInstanceIdentifier=name, IncludeShared=False, IncludePublic=False)
        image = sorted(images.get('DBSnapshots'), key=lambda _: _['SnapshotCreateTime'])[-1]
        _latest_date = self.to_local_tz(image.get('SnapshotCreateTime'))
        logging.info(
            'Latest "%s" snapshot (%s) is taken at %s' % (
                name,
                image['DBSnapshotIdentifier'],
                _latest_date,
            )
        )
        return _latest_date, image

    def wait_until_ec2_available(self, start, instance):
        instance = self.session.resource('ec2').Instance(instance['Instances'][0]['InstanceId'])
        while instance.state['Name'] != 'running':
            logging.info('%s is %s for %s' % (
                self.get_tag(instance.tags, 'Name'),
                instance.state['Name'],
                self.chop_microseconds(datetime.now() - start)))
            time.sleep(15)
            instance.reload()
        logging.info('%s is %s' % (
            self.get_tag(instance.tags, 'Name'),
            instance.state['Name']))
        return instance

    def wait_until_rds_available(self, start, rds_name):
        instance = self.rds.describe_db_instances(
            DBInstanceIdentifier=rds_name)['DBInstances'][0]
        while instance['DBInstanceStatus'] != 'available':
            logging.info('%s is %s for %s' % (
                rds_name,
                instance['DBInstanceStatus'],
                self.chop_microseconds(datetime.now() - start)))
            time.sleep(30)
            instance = self.rds.describe_db_instances(
                DBInstanceIdentifier=rds_name)['DBInstances'][0]
        return instance

    def clone(self, name):
        ec2_instance = self.ec2_lookup(name)
        instance_backup = self.options.image_id or None
        rds_instance = None

        if ec2_instance:
            logging.info('Found ec2 instance "%s"' % name)
            if not instance_backup:
                latest, instance_backup = self.find_latest_ec2_snapshot(name)
                assert instance_backup, "Error: Image is required. Use instances-backup.py to create one"
        else:
            rds_instance = self.rds_lookup(name)
            assert rds_instance, 'Error: Cannot find "%s"' % name
            logging.info('Found rds instance "%s"' % name)
            if not instance_backup:
                latest, instance_backup = self.find_latest_rds_snapshot(name)
                assert instance_backup, "Error: Image is required"

        if ec2_instance:
            try:
                start = datetime.now()
                original_name = self.get_tag(
                    self.session.resource('ec2').Instance(ec2_instance).tags, 'Name')

                new_name = self.options.new_name or '%s-clone%02d%02d%02d' % (
                    original_name,
                    int(start.day),
                    int(start.hour),
                    int(start.minute)
                )

                ec2_instance = self.ec2_res.Instance(ec2_instance)
                instance_type = self.options.instance_type or ec2_instance.instance_type
                user_data = self.options.user_data or USER_DATA
                assert user_data.startswith("#"), "Error: Bad user_data format"
                tags = ec2_instance.tags
                for _ in tags:
                    if _['Key'] == 'Name':
                        _['Value'] = new_name

                instance = self.ec2.run_instances(
                    EbsOptimized=False if instance_type.startswith('t2') else True,
                    IamInstanceProfile=ec2_instance.iam_instance_profile or {},
                    ImageId=instance_backup['ImageId'],
                    InstanceType=instance_type,
                    KeyName=self.options.key_name or ec2_instance.key_name,
                    MaxCount=1,
                    MinCount=1,
                    Monitoring={'Enabled': False},
                    SubnetId=self.options.subnet_id or ec2_instance.network_interfaces_attribute[0]['SubnetId'],
                    TagSpecifications=[
                        {'ResourceType': 'instance', 'Tags': tags},
                        {'ResourceType': 'volume', 'Tags': [
                            {'Key': 'Name', 'Value': "vol-%s" % new_name}]},
                    ],
                    UserData=user_data,
                    DryRun=self.options.dry_run,
                )

                self.ec2.modify_instance_attribute(
                    InstanceId=instance['Instances'][0]['InstanceId'],
                    Groups=self.options.security_group_ids or [
                        _['GroupId'] for _ in ec2_instance.security_groups
                    ],
                )
                self.wait_until_ec2_available(start, instance)
                return instance
            except botocore.exceptions.ClientError as _:
                logging.error(_)

        if rds_instance:
            try:
                start = datetime.now()
                instance = self.rds.restore_db_instance_from_db_snapshot(
                    DBInstanceIdentifier=self.options.new_name or '%s-clone%02d%02d%02d' % (
                        rds_instance['DBInstanceIdentifier'],
                        int(start.day),
                        int(start.hour),
                        int(start.minute)
                    ),
                    AutoMinorVersionUpgrade=True,
                    AvailabilityZone=rds_instance['AvailabilityZone'],
                    CopyTagsToSnapshot=False,
                    DBInstanceClass=self.options.instance_type or rds_instance['DBInstanceClass'],
                    DBSnapshotIdentifier=instance_backup['DBSnapshotIdentifier'],
                    DBSubnetGroupName=rds_instance['DBSubnetGroup']['DBSubnetGroupName'],
                    EnableIAMDatabaseAuthentication=False,
                    Engine=rds_instance['Engine'],
                    Iops=rds_instance['Iops'] if rds_instance.get('Iops') else 0,
                    LicenseModel=rds_instance['LicenseModel'],
                    MultiAZ=False,
                    OptionGroupName=rds_instance['OptionGroupMemberships'][0]['OptionGroupName'],
                    PubliclyAccessible=False,
                    StorageType=rds_instance['StorageType'],
                )
                # tags = self.rds.list_tags_for_resource(
                #     ResourceName=instance['DBInstance']['DBInstanceArn'])['TagList']
                instance and logging.info('rds cloning started: %s, %s, %s, %s' % (
                    instance['DBInstance']['DBInstanceIdentifier'],
                    instance['DBInstance']['DBInstanceClass'],
                    instance['DBInstance']['Engine'],
                    instance['DBInstance']['DBInstanceArn'],
                ))

                rds_name = instance['DBInstance']['DBInstanceIdentifier']
                self.wait_until_rds_available(start, rds_name)

                logging.info('Modifying parameters for %s' % rds_name)
                self.rds.modify_db_instance(
                    ApplyImmediately=True,
                    BackupRetentionPeriod=0,
                    DBInstanceIdentifier=rds_name,
                    DBParameterGroupName=rds_instance['DBParameterGroups'][0]['DBParameterGroupName'],
                    VpcSecurityGroupIds=[_['VpcSecurityGroupId'] for _ in rds_instance['VpcSecurityGroups']],
                )
                self.wait_until_rds_available(start, rds_name)

                for _ in range(3):
                    try:
                        logging.info('Rebooting %s' % rds_name)
                        self.rds.reboot_db_instance(DBInstanceIdentifier=rds_name)
                        break
                    except botocore.exceptions.ClientError as e:
                        if e.response['Error']['Code'] == 'InvalidDBInstanceState':
                            self.wait_until_rds_available(start, rds_name)

                _ = self.wait_until_rds_available(start, rds_name)
                logging.info('Parameters for %s is %s' % (
                    rds_name, _['DBParameterGroups'][0]['ParameterApplyStatus']))
                logging.info('"%s:%s" is available' % (
                    instance['DBInstance']['Endpoint']['Address'],
                    instance['DBInstance']['Endpoint']['Port']
                ))
                return rds_name
            except botocore.exceptions.ClientError as _:
                logging.error(_)

    @staticmethod
    def chop_microseconds(delta):
        return delta - timedelta(microseconds=delta.microseconds)

    @staticmethod
    def get_tag(_tags, tag_name):
        tag = [tag['Value'] for tag in _tags if tag['Key'] == tag_name]
        return tag[0] if tag else 'Unknown'

    @staticmethod
    def to_local_tz(utc_dt):
        return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)


def sigterm_handler(*args):
    sig_name = next(v for v, k in signal.__dict__.items() if k == args[0])
    logging.info('Exiting %s on %s' % (os.getpid(), sig_name))
    exit(0)


def main(args=None):
    args = args or sys.argv[1:]
    my_parser = ArgsParser()
    options = my_parser.parse_args(args)

    for _ in ['boto3', 'botocore']:
        not options.verbose and logging.getLogger(_).setLevel(logging.CRITICAL)

    for _ in [signal.SIGINT, signal.SIGTERM]:
        # noinspection PyTypeChecker
        signal.signal(_, sigterm_handler)

    try:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=options.log_format)
        c = Clone(options)
        c.clone(options.name)

    except (
            AssertionError,
            botocore.exceptions.ClientError,
            botocore.exceptions.NoCredentialsError,
    ) as _:
        raise SystemExit(_)


if __name__ == '__main__':
    main()
