## Synopsis
**cloudwatch-metrics**

Runs as a service on Ubuntu instance. Every 5 minutes posts custom metrics into CloudWatch



| Posted metric  | Comments |
| ------------- | ------------- |
| LoadAverage  | load average|
| MemoryUtilization  | in percent  |
| DiskSpaceUtilization  | in percent for each MountPath  |
| NetworkConnections  | for TCP and UDP  |
| OpenFileDescriptorCount  | number of open files |



## Make

Install prerequisites
```bash
sudo apt-get -qy install python-pip python-dev build-essential virtualenv
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
sudo dpkg -i build/cloudwatch-metrics.deb
```

## Configure

Provide valid AWS CloudWatch credentials using one of the following: 
1. IAM
2. ~root/.aws/credentials
3. ~root/.aws/config
4. /etc/boto.cfg
5. ~root/.boto
6. or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables

## Start

Start service on deprecated (upstart) system
```bash
sudo service cloudwatch-metrics start
```
Start service in systemd
```bash
sudo systemctl start cloudwatch-metrics.service
```

## Set to auto-start

On upstart system
```bash
sudo update-rc.d cloudwatch-metrics enable
```
On a system with systemd 
```bash
sudo systemctl enable cloudwatch-metrics.service
```