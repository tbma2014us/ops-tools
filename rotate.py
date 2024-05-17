#!/usr/bin/env python3
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

default_expiry_threshold_days = 7
default_log_format = '[%(levelname)s] (%(filename)s:%(threadName)s:%(lineno)s) %(message)s'
default_verbose = False


class AWSKey:
    def __init__(self, expiry_threshold_days=None, credentials_file='~/.aws/credentials',
                 backup_file='~/.aws/credentials.old'):
        self.expiry_threshold_days = expiry_threshold_days or default_expiry_threshold_days
        self.session = boto3.Session()
        self.iam = self.session.client('iam')
        self.sts = self.session.client('sts')
        self.credentials_file = Path(credentials_file).expanduser()
        self.backup_file = Path(backup_file).expanduser()
        self.username = self.get_iam_username()

    def get_iam_username(self):
        identity = self.sts.get_caller_identity()
        arn = identity['Arn']
        if arn.endswith(':root'):
            return None
        username = arn.split('/')[-1]
        return username

    def get_access_keys(self):
        if self.username:
            response = self.iam.list_access_keys(UserName=self.username)
        else:
            response = self.iam.list_access_keys()
        return response['AccessKeyMetadata']

    def key_is_expiring_soon(self, access_key):
        create_date = access_key['CreateDate']
        days_elapsed = (datetime.now(create_date.tzinfo) - create_date).days
        return days_elapsed >= self.expiry_threshold_days

    def create_new_access_key(self):
        if self.username:
            response = self.iam.create_access_key(UserName=self.username)
        else:
            response = self.iam.create_access_key()
        return response['AccessKey']

    def delete_access_key(self, access_key_id):
        if self.username:
            self.iam.delete_access_key(UserName=self.username, AccessKeyId=access_key_id)
        else:
            self.iam.delete_access_key(AccessKeyId=access_key_id)

    def backup_credentials_file(self):
        self.backup_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.credentials_file, self.backup_file)

    def update_credentials_file(self, new_access_key):
        config = configparser.ConfigParser()
        config.read(self.credentials_file)

        if 'default' not in config:
            config['default'] = {}

        config['default']['aws_access_key_id'] = new_access_key['AccessKeyId']
        config['default']['aws_secret_access_key'] = new_access_key['SecretAccessKey']

        with open(self.credentials_file, 'w') as configfile:
            config.write(configfile)

    def replace_expiring_keys(self):
        access_keys = self.get_access_keys()

        backed_up = False
        for access_key in access_keys:
            if self.key_is_expiring_soon(access_key):
                if not backed_up:
                    self.backup_credentials_file()
                    logging.info(f"Backup of the credentials file created at {self.backup_file}")
                    backed_up = True
                logging.info(f"Access key {access_key['AccessKeyId']} is expiring soon.")

                new_access_key = self.create_new_access_key()
                logging.info(f"Created new access key: {new_access_key['AccessKeyId']}")

                self.update_credentials_file(new_access_key)
                logging.info("Updated ~/.aws/credentials with new access key.")

                self.delete_access_key(access_key['AccessKeyId'])
                logging.info(f"Deleted old access key: {access_key['AccessKeyId']}")


# noinspection PyTypeChecker,PyUnusedLocal
def sigterm_handler(signum, frame):
    sig_name = signal.Signals(signum).name
    logging.info(f'Exiting {os.getpid()} on {sig_name}')
    sys.exit(0)


if __name__ == "__main__":
    for _ in ['boto3', 'botocore']:
        not default_verbose and logging.getLogger(_).setLevel(logging.CRITICAL)

    for _ in [signal.SIGINT, signal.SIGTERM]:
        # noinspection PyTypeChecker
        signal.signal(_, sigterm_handler)

    try:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=default_log_format)
        aws_key_manager = AWSKey(expiry_threshold_days=7)
        aws_key_manager.replace_expiring_keys()

    except botocore.exceptions.ClientError as _:
        raise SystemExit(_)
