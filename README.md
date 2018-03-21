# python-tools
DevOps tools written in Python
1. [cloudwatch_metrics](#cloudwatch_metrics)
2. [watchdog.py](#watchdog.py)


## cloudwatch_metrics
Service daemon for Ubuntu servers to post custom CloudWatch metrics.
## watchdog.py
TCP-port watchdog. Monitors availability of the TCP port, runs external process if port is unavailable.
```bash
./watchdog.py -a 192.168.1.1 -p 80 -c "echo port unavailable" -r 1
```