## Synopsis
**cloudwatch-metrics**

Runs as a service on Ubuntu instance. Every 5 minutes posts custom metrics into CloudWatch

1. [Make](#make)
2. [Install](#install)
3. [Configure](#configure)
4. [Start](#start)
5. [Set to auto-start](#set-to-auto-start)
6. [Notes](#notes)

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

* Provide valid AWS CloudWatch credentials using one of the following: 
    * IAM
    * ~root/.aws/credentials
    * ~root/.aws/config
    * /etc/boto.cfg
    * ~root/.boto
    * AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables, specified in ```/etc/default/cloudwatch-metrics```

* Edit ```/etc/default/cloudwatch-metrics``` and add necessary options there. For example:
    ```bash
    OPTIONS="--verbose"
    ```
    
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

## Notes

* Typical IAM policy for this service:
    ```json
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": [
                    "cloudwatch:PutMetricData",
                    "cloudwatch:GetMetricStatistics*",
                    "cloudwatch:ListMetrics*",
                    "ec2:DescribeTags*"
                ],
                "Effect": "Allow",
                "Resource": "*"
            }
        ]
    }
    ```
    

* Currently collected metrics:


| Metric  | Comments |
| ------------- | ------------- |
| LoadAverage  | load average|
| MemoryUtilization  | in percent  |
| DiskSpaceUtilization  | in percent for each MountPath  |
| NetworkConnections  | for TCP and UDP  |
| OpenFileDescriptorCount  | number of open files |
