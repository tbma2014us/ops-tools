# python-tools
DevOps tools written in Python
1. [cloudwatch_metrics](cloudwatch_metrics/README.md)
2. [kms_encrypt](kms_encrypt/README.md)
3. [add-tags.py](#add-tags.py)
4. [watchdog.py](#watchdog.py)


## cloudwatch_metrics
Service daemon for Ubuntu servers to post custom CloudWatch metrics.

## kms_encrypt
A set of tools to work with AWS KMS encryption.

## add-tags.py
Adds tags to AWS ec2 instances by name or instance id

## watchdog.py
TCP-port watchdog. Monitors availability of the TCP port, runs external process if port is unavailable.
```bash
./watchdog.py -a 192.168.1.1 -p 80 -c "echo port unavailable" -r 1
```