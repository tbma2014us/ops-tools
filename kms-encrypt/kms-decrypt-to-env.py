#!/usr/bin/env python
import logging
import os
import subprocess
import sys
import cStringIO

import argparse
import aws_encryption_sdk
import boto3
import botocore.exceptions


class ArgsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'description',
            'Decrypts encrypted variable files')
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.formatter_class = argparse.RawTextHelpFormatter
        self.epilog = '\nUse in bash scripts as\n export $(kms-decrypt-to-env secret.env.enc)\n'
        self.options = None
        self.add_argument('-a', '--alias', dest='key_alias', help='KMS key alias', default='alias/ec2')
        self.add_argument('-p', '--profile', dest='profile', help='AWS profile to use')
        self.add_argument('-r', '--region', dest='region', default='us-west-2', help='AWS region to connect')
        self.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Be verbose')
        self.add_argument('in_file', help='Name of the encrypted environment file',)

    def error(self, message):
        sys.stderr.write('Error: %s\n\n' % message)
        self.print_help()
        sys.exit(2)

    def parse_args(self, *args, **kwargs):
        options = argparse.ArgumentParser.parse_args(self, *args, **kwargs)
        options.log_format = '%(filename)s:%(lineno)s[%(process)d]: %(levelname)s %(message)s'
        options.name = os.path.basename(__file__)
        if not options.out_file and options.in_file.endswith('.enc'):
            options.out_file = options.in_file[:-4]
        elif not options.out_file:
            self.error('Please specify output file')
        self.options = options
        return options


class KmsDecryptEnv(object):
    def __init__(self, _session):
        self.session = _session

    def alias_exists(self, _alias):
        aliases = self.session.client('kms').list_aliases()
        return any([k for k in aliases['Aliases'] if k['AliasName'] == _alias])

    def build_kms_master_key_provider(self, alias):
        if not self.alias_exists(alias):
            raise SystemExit('FATAL: alias %s does not exists in %s' % (
                alias,
                self.session.region_name,
            ))
        arn_template = 'arn:aws:kms:{region}:{account_id}:{alias}'
        kms_master_key_provider = aws_encryption_sdk.KMSMasterKeyProvider()
        account_id = self.session.client('sts').get_caller_identity()['Account']
        kms_master_key_provider.add_master_key(arn_template.format(
            region=self.session.region_name,
            account_id=account_id,
            alias=alias
        ))
        return kms_master_key_provider

    def decrypt_file_to_env(self, key_alias, input_filename):
        key_provider = self.build_kms_master_key_provider(key_alias)
        used_keys = []
        output = cStringIO.StringIO()
        p = subprocess.Popen(
            ['/bin/bash'],
            env={},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        with open(input_filename, 'rb') as infile, \
                aws_encryption_sdk.stream(
                    mode='d',
                    source=infile,
                    key_provider=key_provider
                ) as decryptor:
            for chunk in decryptor:
                output.write(chunk)
        output.seek(0)
        for output_line in output:
            (key, _, _) = output_line.partition("=")
            used_keys.append(key)
            p.stdin.write(output_line)
        p.stdin.write('\nset\nexit\n')
        for line in p.stdout:
            (key, _, value) = line.partition("=")
            if key in used_keys:
                print line.strip()


def main(args=sys.argv[1:]):
    my_parser = ArgsParser()
    options = my_parser.parse_args(args)

    for m in ['botocore', 'boto3', 'aws_encryption_sdk']:
        not options.verbose and logging.getLogger(m).setLevel(logging.CRITICAL)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=options.log_format)
    session = boto3.session.Session()

    k = KmsDecryptEnv(session)
    try:
        k.decrypt_file_to_env(
            options.key_alias,
            options.in_file,
        )
    except botocore.exceptions.ClientError as e:
        raise SystemExit(e)


if __name__ == '__main__':
    main()
