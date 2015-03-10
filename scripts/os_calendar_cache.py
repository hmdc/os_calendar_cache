#!/usr/bin/env python

"""
This file is called via a cronjob.
It calls a method in HMDCOutages that handles creating a custom XML file based
on the RCE calendar RSS feed. Outage Notifier will then read that XML file.
"""

from outagenotifier import HMDCOutages
HMDCOutages().createCache()