#!/usr/bin/env python

from icalendar import Calendar
from lxml import etree
import ConfigParser
import datetime
import dateutil.parser
import filecmp
import hashlib
import hmdclogger
import os
import pytz
import re
import shutil
import sys
import time
import urllib2

__author__ = "Harvard-MIT Data Center DevOps"
__copyright__ = "Copyright 2014, HMDC"
__credits__ = ["Bradley Frank"]
__license__ = "GPLv2"
__maintainer__ = "HMDC"
__email__ = "linux@lists.hmdc.harvard.edu"
__status__ = "Production"


class OSCalendarCache:
  """Module for caching and parsing OpenScholar calendar feeds.

  Example:
    cacher = os_calendar_cache.OSCalendarCache()
    cacher.get_updates()

  Public Functions:
    get_updates: Checks the calendar for updates and outputs notifications feed.
    is_resolved: Searches outage description for the resolved string.
    iso_to_unixtime: Converts ISO8601 datetime to a unix timestamp.
    parse_ical: Searches the calendar ICAL feed to parse events.
    sanitize_text: Replaces non-alphanumeric characters with underscores.
    write_xml: Writes an XML file from the data parsed from the calendar feed.

  Class Variables:
    CONFIG_FILE (string): Location of conf file to import self.settings.
  """

  CONFIG_FILE = "/etc/os_calendar_cache.conf"

  def __init__(self, debug_level=None, log_to_console=False, log_to_file=False):
    """Parses the conf file for self.settings, and sets up a logging instance.

    Arguments:
      debug_level (string): Optionally override the debugging level.
      log_to_console (boolean): Optionally log to console.
      log_to_file (boolean): Optionally log to a file (defined in CONFIG_FILE).

    Attributes:
      config (instance): Instance of ConfigParser().
      hmdclog (instance): Instance of HMDCLogger for logging.
    """

    config_name = self.__class__.__name__
    config = ConfigParser.ConfigParser()
    config.read(self.CONFIG_FILE)

    self.settings = {
      # Debugging
      'debug_level': config.get('Debugging', 'debug_level'),
      'log_file': config.get('Debugging', 'log_file'),
      # Parsing
      'resolved_pattern': config.get('Parsing', 'resolved_pattern'),
      # Sources
      'feed_url': config.get('Sources', 'feed_url'),
      'website_url': config.get('Sources', 'website_url'),
      # WorkingFiles
      'cache': config.get('WorkingFiles', 'cache'),
      'notifications': config.get('WorkingFiles', 'notifications'),
      'preserve_versions': config.getboolean('WorkingFiles', 'preserve_versions'),
      'working_directory': config.get('WorkingFiles', 'working_directory'),
    }

    if debug_level is None:
      self.hmdclog = hmdclogger.HMDCLogger(config_name, self.settings['debug_level'])
      self.hmdclog.log_to_file(self.settings['log_file'])
    else:
      self.hmdclog = hmdclogger.HMDCLogger(config_name, debug_level)

      # There must be at least one handler.
      if log_to_console is False and log_to_file is False:
        raise Exception("You must set a logging handler (console or file).")

      # Log to console and/or file.
      if log_to_console:
        self.hmdclog.log_to_console()
      if log_to_file:
        self.hmdclog.log_to_file(self.settings['log_file'])

  def get_updates(self):
    """Detect updates by parsing a cached ICAL feed to a temp file and
    comparing that to the existing notifications XML feed.

    Attributes:
      cache (string): Full path to the cache file.
      date (string): Current date and time for cache filename.
      directory (string): Location of the working directory.
      feed (object): File handler of the feed.
      notifications (string): Full path to the outages file.
      outages (dictionary): Results from parsing the calendar feed.
      preserve (boolean): If true, saves previous cache files.
      temp (string): Full path to the temp file.
    """

    #
    # Set up file locations for sources and outputs.
    #
    directory = self.settings["working_directory"]
    date = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    cache = directory + "/outages-" + date + ".ics"
    temp = directory + "/outages-" + date + ".xml"
    notifications = directory + "/" + self.settings["notifications"]
    preserve = self.settings['preserve_versions']

    self.hmdclog.log('debug', "Cache file: " + cache)
    self.hmdclog.log('debug', "Temp file: " + temp)
    self.hmdclog.log('debug', "Notify feed: " + notifications)
    self.hmdclog.log('debug', "Calendar feed: " + self.settings['feed_url'])
    self.hmdclog.log('debug', "Preserve cache: " + str(preserve))

    #
    # Download a new copy of the calendar feed into a cache file.
    #
    try:
      feed = urllib2.urlopen(self.settings["feed_url"])
      with open(cache, "wb") as file:
          file.write(feed.read())
      file.closed
      self.hmdclog.log('info', "Successfully downloaded the ICAL feed.")
      self.hmdclog.log('debug', "Wrote: " + cache)
    except urllib2.HTTPError, e:
      print("HTTP Error:", e.code, feed)
    except urllib2.URLError, e:
      print("URL Error:", e.reason, feed)

    #
    # Parse the cache file, which strips out only the outage related
    # information. Then save that information to a temp file.
    #
    outages = self.parse_ical(cache)
    self.write_xml(outages, temp)

    #
    # The temp file is compared to the existing notify feed (xml file), in
    # order to determine if anything has changed (i.e. updated). If there's
    # no notify feed yet, force an update.
    #
    if os.path.isfile(notifications):
      self.hmdclog.log('debug', "Comparing temp and notify feed.")
      feed_updated = not filecmp.cmp(temp, notifications)
    else:
      self.hmdclog.log('debug', "No notify feed found; forcing update.")
      feed_updated = True

    #
    # If updates were found, make the temp file the new notify feed.
    # Otherwise, scrap the temp file.
    #
    if feed_updated:
      self.hmdclog.log('info', "Updates to the outages feed were found.")
      shutil.move(temp, notifications)
      self.hmdclog.log('debug', "Temp file converted to new notify feed.")
    else:
      self.hmdclog.log('info', "No updates were found.")
      if preserve is False:
        try:
          os.remove(temp)
        except OSError, e:
          self.hmdclog.log('critical', "Error deleting %s: %s." % (e.filename, e.strerror))
        self.hmdclog.log('debug', "Deleted the temp file.")
      else:
        self.hmdclog.log('debug', "Temp file was preserved.")

    #
    # Delete the cache file.
    #
    if preserve is False:
      try:
        os.remove(cache)
      except OSError, e:
        self.hmdclog.log('critical', "Error deleting %s: %s." % (e.filename, e.strerror))
      self.hmdclog.log('debug', "Deleted the cache file.")
    else:
      self.hmdclog.log('debug', "Cache file was preserved.")

  def is_resolved(self, description):
    """Attempts to find the resolved string with regex.

    Arguments:
        description (string): Description of the outage from the feed.

    Attributes:
        matches (object): Result of searching for resolved pattern.
        resolved_regex (string): Resolved string in regex form.

    Returns:
        matched (boolean): If the resolved string is present.
    """

    resolved_regex = "(.*)(" + self.settings["resolved_pattern"] + ")(.*)"
    self.hmdclog.log('debug', "Resolved regex: " + resolved_regex)

    regex = re.compile(resolved_regex, re.MULTILINE)
    # Cast to bool to get True or False -- we don't want the actual string.
    matched = bool(regex.search(description))

    if matched:
      self.hmdclog.log('debug', "Resolved pattern found!")
    else:
      self.hmdclog.log('debug', "Resolved pattern not found!")

    return matched

  def iso_to_unixtime(self, name, isodate):
    """Converts ISO8601 datetime to a unix timestamp."""

    # From python-dateutil: converts ISO to datetime object.
    dt_object = dateutil.parser.parse(isodate)
    # Converts the datetime object to tuple format.
    dt_tuple = dt_object.timetuple()
    # Converts the tuple into a unix timestamp (floating point).
    timestamp = time.mktime(dt_tuple)
    # Casts the floating point to int.
    timestamp = int(timestamp)

    self.hmdclog.log('debug', "" + name + ": " + str(isodate) +
                     " converted to " + str(timestamp))
    return timestamp

  def parse_ical(self, source):
    """Parses an iCal feed for outage information.

    Arguments:
      source (string): Filename with absolute path of the source file.

    Attributes:
      desc (string): The 'description' from the ICAL feed.
      end_time (int): The 'end time' in unix format from the ICAL feed.
      event_counter (int): Numbers events for debugging.
      link (string): The 'URL' from the ICAL feed.
      mod_time (int): The 'modified time' in unix format from the ICAL feed.
      resolved (boolean): If the outage is marked resolved is the description.
      start_time (int): The 'start time' in unix format from the ICAL feed.
      title (string): The event 'title' from the ICAL feed.

    Returns:
      outages (dictionary): Resulting variables from the parsed iCalendar feed.
    """

    event_counter = 1
    outages = []

    if os.path.isfile(source):
      with open(source, "rb") as file:
        ical_feed = Calendar.from_ical(file.read())
      file.closed
      self.hmdclog.log('debug', "Read in file: " + source)
    else:
      raise Exception("ICAL feed not found!")

    for component in ical_feed.walk():
      if component.name == "VEVENT":
        self.hmdclog.log('debug', "")
        self.hmdclog.log('debug', "Begin parsing event #" + str(event_counter) + ".")

        desc = component.get("DESCRIPTION").encode('utf-8')
        self.hmdclog.log('debug', "Description:\n" + desc + "\n")

        end_time = component.get('DTEND').to_ical()
        end_time = self.iso_to_unixtime("Endtime", end_time)

        link = component.get('URL')
        self.hmdclog.log('debug', "URL: " + link)

        mod_time = component.get('LAST-MODIFIED').to_ical()
        mod_time = self.iso_to_unixtime("Modtime", mod_time)

        resolved = self.is_resolved(desc)
        self.hmdclog.log('debug', "Resolved: " + str(resolved))

        start_time = component.get('DTSTART').to_ical()
        start_time = self.iso_to_unixtime("Starttime", start_time)

        title = self.sanitize_text("Title", component.get('SUMMARY'))

        self.hmdclog.log('debug', "Done parsing event #" + str(event_counter) + ".")

        #
        # If there's no end time defined, ICAL sets it to be equal to
        # the start time, which we don't want - so zero it out.
        #
        if end_time == start_time:
          end_time = "0" * 10
          self.hmdclog.log('debug', "Found matching start and end time.")

        outages.append({"end_time": str(end_time),
                        "link": str(link),
                        "mod_time": str(mod_time),
                        "resolved": str(resolved),
                        "start_time": str(start_time),
                        "title": title})

        event_counter += 1

    self.hmdclog.log('debug', "")
    self.hmdclog.log('info', "Parsed " + str(event_counter) + " event(s).")
    return outages

  def sanitize_text(self, name, text):
    """Replaces non-alphanumeric characters with underscores."""

    pattern = re.compile(r'[^\w\s]', re.MULTILINE)
    subbed = re.sub(pattern, "_", str(text))
    self.hmdclog.log('debug', "" + name + ": \"" + str(text) +
                     "\" converted to " + "\"" + str(subbed) + "\"")
    return subbed

  def write_xml(self, outages, output):
    """Writes an XML file from the data parsed from the calendar feed.

    Arguments:
        outages (list): Parsed elements of the outages feed.
        output (string): Filename with absolute path of the output file.

    Attributes:
        event_counter (int): Numbers events for debugging.
        root (object): Top element in the XML tree.
        tree (object): Wrapper to save elements in XML format.
    """

    event_counter = 1
    root = etree.Element("outages")
    tree = etree.ElementTree(root)

    for outage in outages:
      #
      # Create a subelement for each outage:
      #   o title (the name of the ouage)
      #   o link (URL to the calendar event)
      #   o resolved (boolean, if the event is resolved)
      #   o start_time (the event's start time)
      #   o end_time (the event's end time)
      #   o mod_time (last modification time)
      #
      self.hmdclog.log('debug', "")
      self.hmdclog.log('debug', "Creating subelements for event #" + str(event_counter) + ".")

      item = etree.SubElement(root, "item")

      title = etree.SubElement(item, "title")
      title.text = outage["title"]

      link = etree.SubElement(item, "link")
      link.text = outage["link"]

      resolved = etree.SubElement(item, "resolved")
      resolved.text = outage["resolved"]

      start_time = etree.SubElement(item, "start_time")
      start_time.text = outage["start_time"]

      end_time = etree.SubElement(item, "end_time")
      end_time.text = outage["end_time"]

      mod_time = etree.SubElement(item, "mod_time")
      mod_time.text = outage["mod_time"]

      self.hmdclog.log('debug', "Completed creating subelements for event #" + str(event_counter) + ".")

      event_counter += 1

    self.hmdclog.log('debug', "")
    with open(output, 'w') as file:
      # The "pretty_print" argument writes the XML in tree form.
      tree.write(file, pretty_print=True, xml_declaration=True)
    file.closed
    self.hmdclog.log('info', "Wrote " + output)


if __name__ == '__main__':
  pass
