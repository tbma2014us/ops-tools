# ops-tools
DevOps tools written in Python
1. [cloudwatch_metrics](cloudwatch_metrics/)
2. [add-tags.py](#add-tagspy)
3. [clone.py](#clonepy)
4. [instances-backup.py](#instances-backuppy)
5. [rotate.py](#rotatepy)
6. [start-stop.py](#start-stoppy)
7. [wait.py](#waitpy)
8. [watchdog.py](#watchdogpy)


## cloudwatch_metrics
Service daemon for Ubuntu servers to post custom AWS CloudWatch metrics.

## add-tags.py
Adds tags to AWS EC2 instances by name or instance id

## clone.py
Creates a clone of the running AWS EC2 or RDS instance by name or instance id

## instances-backup.py
Multithreading AWS EC2 instances backup into AMIs by tag, instance id or name

## rotate.py
Rotates the expiring AWS keys and writes them into the local config files.

## start-stop.py
Starts or stops AWS EC2 instances by name or instance id

## wait.py

Wait for remote SSH service to come back after a boot or reboot

## watchdog.py
TCP-port watchdog. Monitors availability of the TCP port, runs external process if port is unavailable.
```bash
./watchdog.py -a 192.168.1.1 -p 80 -c "echo port unavailable" -r 1
```


[![APACHE 2.0](https://img.shields.io/badge/License-Apache%202.0-brightgreen.svg?longCache=true&style=for-the-badge)](LICENSE)
[![python](https://img.shields.io/badge/Python-3.6-3776AB.svg?logo=python&logoColor=white&longCache=true&style=for-the-badge)](https://www.python.org)
[![!#/bin/bash](https://img.shields.io/badge/-%23!%2Fbin%2Fbash-1f425f.svg?longCache=true&style=for-the-badge)](https://www.gnu.org/software/bash/)
