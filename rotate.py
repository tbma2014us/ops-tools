#!/usr/bin/env python3
import argparse
import boto3
import botocore.exceptions
import configparser
import logging
import os
import shutil
import signal
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_EXPIRY_THRESHOLD_DAYS = 30 - 7
DEFAULT_LOG_FORMAT = '[%(levelname)s] (%(filename)s:%(threadName)s:%(lineno)s) %(message)s'


class AWSKey:
    def __init__(self, expiry_threshold_days=None, credentials_file='~/.aws/credentials',
                 backup_file='~/.aws/credentials.old', options=None):
        self.backed_up = False
        self.options = options
        self.expiry_threshold_days = expiry_threshold_days or DEFAULT_EXPIRY_THRESHOLD_DAYS
        self.session = boto3.Session()
        self.credentials_file = Path(credentials_file).expanduser()
        self.backup_file = Path(backup_file).expanduser()
        self.config = configparser.ConfigParser()
        self.config.read(self.credentials_file)

    @staticmethod
    def get_iam_username(session):
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        arn = identity['Arn']
        if arn.endswith(':root'):
            return None
        username = arn.split('/')[-1]
        return username

    @staticmethod
    def get_access_keys(iam, username):
        if username:
            response = iam.list_access_keys(UserName=username)
        else:
            response = iam.list_access_keys()
        return response['AccessKeyMetadata']

    def key_is_expiring_soon(self, access_key):
        create_date = access_key['CreateDate']
        days_elapsed = (datetime.now(create_date.tzinfo) - create_date).days
        return days_elapsed >= self.expiry_threshold_days

    @staticmethod
    def create_new_access_key(iam, username):
        if username:
            response = iam.create_access_key(UserName=username)
        else:
            response = iam.create_access_key()
        return response['AccessKey']

    @staticmethod
    def delete_access_key(iam, username, access_key_id):
        if username:
            iam.delete_access_key(UserName=username, AccessKeyId=access_key_id)
        else:
            iam.delete_access_key(AccessKeyId=access_key_id)

    def backup_credentials_file(self):
        self.backup_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.credentials_file, self.backup_file)

    def update_credentials_file(self, profile, new_access_key):
        if profile not in self.config:
            self.config[profile] = {}

        self.config[profile]['aws_access_key_id'] = new_access_key['AccessKeyId']
        self.config[profile]['aws_secret_access_key'] = new_access_key['SecretAccessKey']

        with open(self.credentials_file, 'w') as configfile:
            self.config.write(configfile)

    def replace_expiring_keys(self):
        for profile in self.config.sections():
            self.options.verbose and logging.info(f"Found profile: {profile}")
            session = boto3.Session(profile_name=profile)
            iam = session.client('iam')
            username = self.get_iam_username(session)
            access_keys = self.get_access_keys(iam, username)

            for access_key in access_keys:
                self.options.verbose and logging.info(f"Found access_key: {access_key['AccessKeyId']}")
                if self.key_is_expiring_soon(access_key):
                    if not self.backed_up:
                        self.backup_credentials_file()
                        logging.info(f"Backup of the credentials file created at {self.backup_file}")
                        self.backed_up = True
                    logging.info(f"Access key {access_key['AccessKeyId']} is expiring soon.")

                    new_access_key = self.create_new_access_key(iam, username)
                    logging.info(f"Created new access key: {new_access_key['AccessKeyId']}")

                    self.update_credentials_file(profile, new_access_key)
                    logging.info("Updated ~/.aws/credentials with new access key.")

                    self.delete_access_key(iam, username, access_key['AccessKeyId'])
                    logging.info(f"Deleted old access key: {access_key['AccessKeyId']}")


# noinspection PyTypeChecker,PyUnusedLocal
def sigterm_handler(signum, frame):
    sig_name = signal.Signals(signum).name
    logging.info(f'Exiting {os.getpid()} on {sig_name}')
    sys.exit(0)


if __name__ == "__main__":
    my_parser = argparse.ArgumentParser(description="Rotate AWS keys")
    my_parser.add_argument('-v', '--verbose', action='store_true', help='Be verbose')
    options = my_parser.parse_args()

    for _ in ['boto3', 'botocore']:
        not options.verbose and logging.getLogger(_).setLevel(logging.CRITICAL)

    for _ in [signal.SIGINT, signal.SIGTERM]:
        # noinspection PyTypeChecker
        signal.signal(_, sigterm_handler)

    try:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=DEFAULT_LOG_FORMAT)
        aws_key_manager = AWSKey(options=options)
        aws_key_manager.replace_expiring_keys()

    except botocore.exceptions.ClientError as _:
        raise SystemExit(_)
