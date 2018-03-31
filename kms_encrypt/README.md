## Synopsis
**kms-encrypt**

Encrypts and decrypts files with AWS KMS keys

1. [Make](#make)
2. [Install](#install)
3. [Configure](#configure)

## Make

Install prerequisites
```bash
sudo apt-get -qy install python-pip python-dev build-essential virtualenv libssl-dev libffi-dev
```

Make package
```bash
make
```
makes .deb package in build/

## Install

```bash
sudo make install
```
or
```bash
sudo dpkg -i build/kms-encrypt.deb
```

This installs ```kms-encrypt```, ```kms-decrypt```, and ```kms-decrypt-to-env``` binary executables  in /usr/bin

## Configure

* Provide valid AWS credentials using one of the following: 
    * IAM
    * ~root/.aws/credentials
    * ~root/.aws/config
    * /etc/boto.cfg
    * ~root/.boto
    * ```AWS_ACCESS_KEY_ID``` and ```AWS_SECRET_ACCESS_KEY``` environment variables

