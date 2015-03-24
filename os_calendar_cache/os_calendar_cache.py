#!/usr/bin/env python

from termcolor import colored
from icalendar import Calendar
from lxml import etree
import ConfigParser
import datetime
import dateutil.parser
import filecmp
import hmdclogger
import os
import pytz
import re
import shutil
import sys
import time
import urllib2

__author__ = "Harvard-MIT Data Center DevOps"
__copyright__ = "Copyright 2015, HMDC"
__credits__ = ["Bradley Frank"]
__license__ = "GPLv2"
__maintainer__ = "HMDC"
__email__ = "linux@lists.hmdc.harvard.edu"
__status__ = "Production"


class OSCalendarCache():
  """Module for caching and parsing OpenScholar calendar feeds.

  Example:
    import os_calendar_cache
    cacher = os_calendar_cache.OSCalendarCache()
    cacher.get_updates()

  Private Functions:
    _get_settings: Parses the conf file for settings.
    _set_logger: Creates a logger.

  Public Functions:
    cache_feed: Downloads and caches the calendar ICAL feed.
    create_notifications: Builds console and widget output from outage data.
    format_date: Converts unix timestamp to human readable format.
    get_updates: Checks the calendar for updates and outputs notifications feed.
    is_resolved: Searches outage description for the resolved string.
    iso_to_unixtime: Converts ISO8601 datetime to a unix timestamp.
    notifications_to_xml: Writes console and widget output to an XML file.
    outages_to_xml: Writes a set of data to a file in XML format.
    parse_ical: Searches the ICAL feed to parse events.
    sanitize_text: Replaces non-alphanumeric characters with underscores.
    sort_outages: Sorts outages into one of three categories based on status.
    within_grace_period: Allows ICAL download to fail within a grace period.

  Class Variables:
    CONFIG_FILE (string): Location of conf file to import self.settings.
  """

  CONFIG_FILE = "/etc/os_calendar_cache.conf"

  def __init__(self, debug_level=None, log_to_console=False, log_to_file=False):
    """Sets up module settings and a logging instance.

    Parameters:
      debug_level (string): Optionally override the debugging level.
      log_to_console (boolean): Optionally log to console.
      log_to_file (boolean): Optionally log to a file (defined in CONFIG_FILE).

    Attributes:
      hmdclog (instance): Instance of HMDCLogger for logging.
    """

    self.settings = self._get_settings()
    self.hmdclog = self._set_logger(debug_level, log_to_console, log_to_file)

  def _get_settings(self):
    """Parses the conf file for settings."""

    config = ConfigParser.ConfigParser()
    config.read(self.CONFIG_FILE)

    settings = {
      # Debugging
      'debug_level': config.get('Debugging', 'debug_level'),
      'log_file': config.get('Debugging', 'log_file'),
      # Parsing
      'resolved_pattern': config.get('Parsing', 'resolved_pattern'),
      'scope_ahead': config.getint('Parsing', 'scope_ahead'),
      'scope_past': config.getint('Parsing', 'scope_past'),
      # States
      'states': {},
      # Sources
      'feed_url': config.get('Sources', 'feed_url'),
      'url_timeout': config.getint('Sources', 'url_timeout'),
      'website_url': config.get('Sources', 'website_url'),
      # WorkingFiles
      'working_directory': config.get('WorkingFiles', 'working_directory'),
    }

    for state in ('active', 'completed', 'default', 'error', 'none', 'scheduled'):
      icon, timeout, urgency = config.get('States', state).split(':')
      settings['states'][state] = {
        'icon': icon,
        'timeout': int(timeout),
        'urgency': urgency
      }

    return settings

  def _set_logger(self, debug_level, log_to_console, log_to_file):
    """Creates an instance of HMDCLogger with appropriate handlers."""

    config_name = self.__class__.__name__

    if debug_level is None:
      hmdclog = hmdclogger.HMDCLogger(config_name, self.settings['debug_level'])
      hmdclog.log_to_file(self.settings['log_file'])
    else:
      hmdclog = hmdclogger.HMDCLogger(config_name, debug_level)

      # There must be at least one handler.
      if log_to_console is False and log_to_file is False:
        raise Exception("You must set a logging handler (console or file).")

      # Log to console and/or file.
      if log_to_console:
        hmdclog.log_to_console()
      if log_to_file:
        hmdclog.log_to_file(self.settings['log_file'])

    return hmdclog

  def cache_feed(self, cache_file, feed_url, within_grace_period):
    """Downloads and caches the calendar ICAL feed.

    Parameters:
      cache_file (string): Full path to the cache file to save to.
      feed_url (string): URL of the OpenScholar ICAL feed.
      within_grace_period (boolean): If still within the grace period for no
        OpenScholar connectivity.

    Attributes:
      feed (object): File handler of the calendar feed.
    """

    connection_msg = "Unable to connect to OpenScholar: " + feed_url
    timeout_msg = "Cannot download " + feed_url + ", but within grace period."

    try:
      feed = urllib2.urlopen(feed_url)
      with open(cache_file, 'wb') as file:
        file.write(feed.read())
      self.hmdclog.log('debug', "Successfully wrote: " + cache_file)
    #
    # There was an error connecting or download the feed, catch it here but
    # only if it's past the grace period.
    #
    except urllib2.HTTPError, e:
      if not within_grace_period:
        self.hmdclog.log('error', connection_msg)
        raise Exception(connection_msg)
      else:
        self.hmdclog.log('warning', timeout_msg)
        return False
    except urllib2.URLError, e:
      if not within_grace_period:
        self.hmdclog.log('error', connection_msg)
        raise Exception(connection_msg)
      else:
        self.hmdclog.log('warning', timeout_msg)
        return False

    return True

  def create_notifications(self, sorted_outages):
    """Creates notification output for console and widgets based on status.

    Arguments:
      sorted_outages (dictionary): Outages sorted into groups.

    Attributes:
      cli_text (string): Link header text for printing to console.
      counter (int): Counts interations for debugging text.
      gui_text (string): Link header text for displaying to the widget.
      icon (string): Icon to use with associated outage status.
      link_color (string): Shared text color for URLs.
      timeout (int): Time to keep the widget displayed (milliseconds).
      title (string): Name of the outage.
      tooltip (string): Formatted text to display on the widget or console.
      urgency (string): Urgency level used by NOTIFY_SEND.

    Returns:
      output (dictionary): GUI and console output sorted into lists.
    """

    cli_text = "Please see the following URL for more information:"
    gui_text = "Right click the outages toolbar icon for more information."
    link_color = 'blue'
    output = {'gui': [], 'console': []}

    #
    # Create output for all completed outages.
    #
    counter = 0
    for completed in sorted_outages['completed']:
      counter += 1
      self.hmdclog.log('debug', "")
      self.hmdclog.log('debug', "Begin creating output for completed outage #" + str(counter) + ".")
      #
      # Completed outages without a specific end time won't display
      # at all; see sort_outages() for more information.
      #
      title = completed['title']
      complete_text = title + " is now complete."

      #
      # GUI output
      #
      icon = self.settings['states']['completed']['icon']
      tooltip = complete_text + "\n" + gui_text
      timeout = self.settings['states']['completed']['timeout']
      urgency = self.settings['states']['completed']['urgency']

      output['gui'].append({'icon': icon, 'tooltip': tooltip, 'timeout': timeout,
                  'title': title, 'urgency': urgency})

      self.hmdclog.log('debug', "GUI settings:")
      self.hmdclog.log('debug', "\tTitle: " + title)
      self.hmdclog.log('debug', "\tIcon: " + str(icon))
      self.hmdclog.log('debug', "\tTimeout: " + str(timeout))
      self.hmdclog.log('debug', "\tUrgency: " + str(urgency))

      #
      # Console output
      #
      link = colored(completed['link'], link_color)
      text = colored(complete_text, 'yellow', attrs=['bold'])
      tooltip = text + "\n" + cli_text + "\n\t" + link + "\n"
      output['console'].append(tooltip)

      self.hmdclog.log('debug', "Console output:")
      self.hmdclog.log('debug', "\tText: " + str(complete_text))

      self.hmdclog.log('info', "Finished creating output for completed outage #" + str(counter) + ".")

    #
    # Create output for upcoming outages.
    #
    counter = 0
    for scheduled in sorted_outages['scheduled']:
      counter += 1
      self.hmdclog.log('debug', "")
      self.hmdclog.log('debug', "Begin creating output for scheduled outage #" + str(counter) + ".")

      start_time = self.format_date(scheduled['start_time'], 'start_time')
      title = scheduled['title']
      scheduled_text = title + " is scheduled to start on " + start_time

      #
      # GUI output
      #
      icon = self.settings['states']['scheduled']['icon']
      tooltip = scheduled_text + "\n" + scheduled['link'] + "\n" + gui_text
      timeout = self.settings['states']['scheduled']['timeout']
      urgency = self.settings['states']['scheduled']['urgency']

      output['gui'].append({'icon': icon, 'tooltip': tooltip, 'timeout': timeout,
                  'title': title, 'urgency': urgency})

      self.hmdclog.log('debug', "GUI settings:")
      self.hmdclog.log('debug', "\tTitle: " + title)
      self.hmdclog.log('debug', "\tIcon: " + str(icon))
      self.hmdclog.log('debug', "\tTimeout: " + str(timeout))
      self.hmdclog.log('debug', "\tUrgency: " + str(urgency))

      #
      # Console output
      #
      link = colored(scheduled['link'], link_color)
      text = colored(scheduled['title'], attrs=['bold']) + \
        " is scheduled to start on " + colored(start_time, 'green') + "."
      tooltip = text + "\n" + cli_text + "\n\t" + link + "\n"
      output['console'].append(tooltip)

      self.hmdclog.log('debug', "Console output:")
      self.hmdclog.log('debug', "\tText: " + str(scheduled_text))

      self.hmdclog.log('info', "Finished creating output for scheduled outage #" + str(counter) + ".")

    #
    # Create output for all outages currently in progress.
    #
    counter = 0
    for active in sorted_outages['active']:
      counter += 1
      self.hmdclog.log('debug', "")
      self.hmdclog.log('debug', "Begin creating output for active outage #" + str(counter) + ".")

      # If end_time exists, add it to the output.
      if active['end_time'] != 0:
        end_time = " until " + self.format_date(active['end_time'], 'end_time')
      else:
        end_time = ""

      title = active['title']
      active_text = title + " is in progress" + end_time

      #
      # GUI output
      #
      icon = self.settings['states']['active']['icon']
      timeout = self.settings['states']['active']['timeout']
      urgency = self.settings['states']['active']['urgency']
      tooltip = active_text + "." + "\n" + gui_text

      output['gui'].append({'icon': icon, 'tooltip': tooltip, 'timeout': timeout,
                  'title': title, 'urgency': urgency})

      self.hmdclog.log('debug', "GUI settings:")
      self.hmdclog.log('debug', "\tTitle: " + title)
      self.hmdclog.log('debug', "\tIcon: " + str(icon))
      self.hmdclog.log('debug', "\tTimeout: " + str(timeout))
      self.hmdclog.log('debug', "\tUrgency: " + str(urgency))

      #
      # Console output
      #
      link = colored(active['link'], link_color)
      text = colored(active['title'], attrs=['bold']) + \
        colored(" is in progress" + end_time + ".", 'red', attrs=['bold'])
      tooltip = text + "\n" + cli_text + "\n\t" + link + "\n"
      output['console'].append(tooltip)

      self.hmdclog.log('debug', "Console output:")
      self.hmdclog.log('debug', "\tText: " + str(active_text))

      self.hmdclog.log('info', "Done creating output for active outage #" + str(counter) + ".")

    return output

  def format_date(self, unixtime, name):
    """Formats a unix timestamp into a readable date and time."""

    datetime_obj = datetime.datetime.fromtimestamp(unixtime)
    timestamp = datetime_obj.strftime("%B %d at %I:%M") + datetime_obj.strftime("%p").lower()
    self.hmdclog.log('debug', "" + name + ": " + str(unixtime) + " converted to " + str(timestamp))

    return timestamp

  def get_updates(self):
    """Detect updates by parsing a cached calendar feed to a temp file and
    comparing that to the existing notifications feed.

    Attributes:
      cache_file (string): Full path to the cache file.
      cached (boolean): If caching calendar feed succeeded or not.
      directory (string): Location of the working directory.
      feed (object): File handler of the calendar feed.
      feed_updated (boolean): Whether the feed has been updated or not.
      feed_url_safe (string): Filename safe url of the feed.
      parsed_file (string): Full path to the XML file of the parsed feed.
      outages (dictionary): Results from parsing the calendar feed.
      notifications_file (string): Full path to the notifications file.
      temp_file (string): Full path to the temp XML file of the parsed feed.
      within_grace_period (boolean): If still within the grace period for no
        OpenScholar connectivity.
    """

    #
    # Set up file locations for sources and outputs.
    #
    directory = self.settings['working_directory']
    feed_url_safe = self.sanitize_text("feed_url_safe", self.settings['feed_url'])
    cache_file = directory + "/" + feed_url_safe + ".ics"
    notifications_file = directory + "/notifications.xml"
    temp_file = directory + "/notifications-new.xml"

    self.hmdclog.log('debug', "Calendar feed: " + self.settings['feed_url'])
    self.hmdclog.log('debug', "Files:")
    self.hmdclog.log('debug', "\tCache: " + cache_file)
    self.hmdclog.log('debug', "\tTemp: " + temp_file)
    self.hmdclog.log('debug', "\tNotifications: " + notifications_file)

    #
    # Determines if the last cache file was downloaded within the grace
    # period by comparing the timeout setting to the cache file's mtime.
    #
    within_grace_period = self.within_grace_period(cache_file, self.settings['url_timeout'])
    self.hmdclog.log('debug', "Within grace period: " + str(within_grace_period))

    #
    # Download a new copy of the calendar feed into a cache file.
    #
    cached = self.cache_feed(cache_file, self.settings['feed_url'], within_grace_period)

    if cached:
      #
      # Parse the cache file into outages, then notifications.
      #
      outages = self.parse_ical(cache_file)
      sorted_outages = self.sort_outages(outages)
      notifications = self.create_notifications(sorted_outages)
      self.notifications_to_xml(notifications, temp_file)
      #
      # If notifications have not been created previously, force an update;
      # otherwise compare the new temp XML file to the notifications XML file
      # to determine if there are any updates (or changes).
      #
      if not os.path.isfile(notifications_file):
        self.hmdclog.log('debug', "No notifications found; forcing update.")
        feed_updated = True
      else:
        self.hmdclog.log('debug', "Comparing temp file and notifications.")
        feed_updated = not filecmp.cmp(temp_file, notifications_file)
    else:
      feed_updated = False

    #
    # If updates were found, make the temp file the new notifications file.
    # Otherwise, delete the temp file.
    #
    if feed_updated:
      self.hmdclog.log('debug', "Updates to the outages feed were found.")
      shutil.move(temp_file, notifications_file)
      self.hmdclog.log('debug', "Temp file converted to new notifications file.")
    else:
      self.hmdclog.log('info', "No updates were found.")
      if os.path.isfile(temp_file):
        try:
          os.remove(temp_file)
          self.hmdclog.log('debug', "Deleted " + temp_file)
        except OSError, e:
          self.hmdclog.log('error', "Error deleting " + temp_file)

  def is_resolved(self, description):
    """Attempts to find the resolved string with regex.

    Parameters:
        description (string): Description of the outage from the feed.

    Attributes:
        matches (object): Result of searching for resolved pattern.
        resolved_regex (string): Resolved string in regex form.

    Returns:
        matched (boolean): If the resolved string is present.
    """

    resolved_regex = "(.*)(" + self.settings['resolved_pattern'] + ")(.*)"
    self.hmdclog.log('debug', "Resolved regex: " + resolved_regex)

    regex = re.compile(resolved_regex, re.MULTILINE)
    # Cast to bool to get True or False -- we don't want the actual string.
    matched = bool(regex.search(description))

    if matched:
      self.hmdclog.log('debug', "Resolved pattern found.")
    else:
      self.hmdclog.log('debug', "Resolved pattern not found.")

    return matched

  def iso_to_unixtime(self, name, isodate):
    """Converts ISO8601 datetime to a unix timestamp."""

    # From python-dateutil: converts ISO to datetime object.
    dt_object = dateutil.parser.parse(isodate)
    # Converts the datetime object to tuple format.
    dt_tuple = dt_object.timetuple()
    # Converts the tuple into a unix timestamp (and casts to int).
    timestamp = int(time.mktime(dt_tuple))

    self.hmdclog.log('debug', "" + name + ": " + str(isodate) +
                     " converted to " + str(timestamp))
    return timestamp

  def notifications_to_xml(self, notifications, output_file):
    """Writes an XML file from the outages parsed from the calendar feed.

    Parameters:
        notifications (dictionary): Notifications created from parsed outages.
        output_file (string): Full path to the output file.

    Attributes:
        counter (int): Enumerates data items for debugging.
        root (object): Top element in the XML tree.
        tree (object): Wrapper to save elements in XML format.
    """

    root = etree.Element('notifications')
    tree = etree.ElementTree(root)
    self.hmdclog.log('debug', "")

    counter = 0
    messages = etree.SubElement(root, 'messages')
    for outage in notifications['console']:
      counter += 1
      self.hmdclog.log('debug', "Adding message #" + str(counter) + ".")

      message = etree.SubElement(messages, 'message')
      message.text = outage.encode('unicode_escape')

    counter = 0
    widgets = etree.SubElement(root, 'widgets')
    for outage in notifications['gui']:
      counter += 1
      self.hmdclog.log('debug', "Adding widget #" + str(counter) + ".")

      widget = etree.SubElement(widgets, 'widget')

      title = etree.SubElement(widget, 'title')
      title.text = outage['title']

      icon = etree.SubElement(widget, 'icon')
      icon.text = outage['icon']

      tooltip = etree.SubElement(widget, 'tooltip')
      tooltip.text = outage['tooltip']

      timeout = etree.SubElement(widget, 'timeout')
      timeout.text = str(outage['timeout'])

      urgency = etree.SubElement(widget, 'urgency')
      urgency.text = outage['urgency']

    with open(output_file, 'w') as file:
      # The "pretty_print" parameter writes the XML in tree form.
      tree.write(file, pretty_print=True, xml_declaration=True)
    self.hmdclog.log('debug', "")
    self.hmdclog.log('info', "Wrote " + output_file)

  def outages_to_xml(self, outages, output_file):
    """Writes an XML file from the data parsed from the calendar feed.

    Parameters:
        outages (dictionary): Outages parsed from the calendar feed.
        output_file (string): Full path to the output file.

    Attributes:
        counter (int): Enumerates data items for debugging.
        root (object): Top element in the XML tree.
        tree (object): Wrapper to save elements in XML format.
    """

    counter = 0
    self.hmdclog.log('debug', "")
    root = etree.Element('events')
    tree = etree.ElementTree(root)

    for outage in outages:
      counter += 1
      self.hmdclog.log('debug', "Creating subelements for outage #" + str(counter) + ".")

      item = etree.SubElement(root, 'item')

      title = etree.SubElement(item, 'title')
      title.text = outage['title'].encode('utf-8')

      link = etree.SubElement(item, 'link')
      link.text = outage['link'].encode('utf-8')

      resolved = etree.SubElement(item, 'resolved')
      resolved.text = str(outage['resolved'])

      start_time = etree.SubElement(item, 'start_time')
      start_time.text = str(outage['start_time'])

      end_time = etree.SubElement(item, 'end_time')
      end_time.text = str(outage['end_time'])

      mod_time = etree.SubElement(item, 'mod_time')
      mod_time.text = str(outage['mod_time'])

    with open(output_file, 'w') as file:
      # The "pretty_print" argument writes the XML in tree form.
      tree.write(file, pretty_print=True, xml_declaration=True)
    self.hmdclog.log('debug', "")
    self.hmdclog.log('info', "Wrote " + output_file)

  def parse_ical(self, source):
    """Parses an iCal feed for events.

    Parameters:
      source (string): Filename with absolute path of the source file.

    Attributes:
      counter (int): Numbers events for debugging.
      desc (string): The 'description' from the calendar feed.
      end_time (int): The 'end time' in unix format from the calendar feed.
      link (string): The 'URL' from the calendar feed.
      mod_time (int): The 'modified time' in unix format from the calendar feed.
      resolved (boolean): If the outage is marked resolved is the description.
      start_time (int): The 'start time' in unix format from the calendar feed.
      title (string): The event 'title' from the calendar feed.

    Returns:
      outages (dictionary): Resulting variables from the parsed calendar feed.
    """

    counter = 0
    outages = []

    if os.path.isfile(source):
      with open(source, 'rb') as file:
        ical_feed = Calendar.from_ical(file.read())
      self.hmdclog.log('debug', "Read in file: " + source)
    else:
      raise Exception("Calendar feed not found!")

    for component in ical_feed.walk():
      if component.name == "VEVENT":
        counter += 1
        self.hmdclog.log('debug', "")
        self.hmdclog.log('debug', "Begin parsing entry #" + str(counter) + ".")

        desc = component.get("DESCRIPTION").encode('utf-8')
        self.hmdclog.log('debug', "(Description parsed.)")

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

        title = component.get('SUMMARY').encode('utf-8')
        title = self.sanitize_text("title", title)

        self.hmdclog.log('debug', "Done parsing entry #" + str(counter) + ".")

        #
        # If there's no end time defined, ICAL sets it to be equal to
        # the start time, which we don't want -- so zero it out.
        #
        if end_time == start_time:
          end_time = "0" * 10
          self.hmdclog.log('debug', "Found matching start and end time.")

        outages.append({'end_time': end_time,
                        'link': link,
                        'mod_time': mod_time,
                        'resolved': resolved,
                        'start_time': start_time,
                        'title': title})

    return outages

  def sanitize_text(self, name, text):
    """Replaces non-alphanumeric characters with underscores."""

    pattern = re.compile(r'[^\w\s]', re.MULTILINE)
    subbed = re.sub(pattern, "_", str(text))
    self.hmdclog.log('debug', "" + name + ": \"" + str(text) +
                     "\" converted to " + "\"" + str(subbed) + "\"")
    return subbed

  def sort_outages(self, outages):
    """Sorts outages into groups of "completed", "active", and "scheduled".

    Parameters:
      outages (dictionary): A list of outages from the calendar feed.

    Attributes:
      counter (int): Counts interations for debugging text.
      now (int): Current date and time as a unix timestamp.

    Returns:
      sorted_outages (dictionary): Outages sorted into buckets of
        "completed", "active", and "scheduled".
    """

    counter = 0
    sorted_outages = {'completed': [], 'scheduled': [], 'active': []}
    now = int(time.time())

    #
    # Iterate over each outage and sort it based on several factors.
    #
    for outage in outages:
      counter += 1
      self.hmdclog.log('debug', "")
      self.hmdclog.log('debug', "Begin sorting outage #" +
               str(counter) + ": " + outage["title"])

      #
      # Calculates how many seconds until the start and end time.
      #
      seconds_until_start = outage['start_time'] - now
      seconds_until_end = outage['end_time'] - now
      self.hmdclog.log('debug', "seconds until start: " + str(seconds_until_start))
      self.hmdclog.log('debug', "seconds until end: " + str(seconds_until_end))

      #
      # Determines if the outage has started and ended.
      #
      has_started = seconds_until_start <= 0
      has_ended = seconds_until_end <= 0
      self.hmdclog.log('debug', "has started: " + str(has_started))
      self.hmdclog.log('debug', "has ended: " + str(has_ended))

      #
      # Some outages may not have a defined end time.
      #
      has_end_time = outage['end_time'] != 0
      self.hmdclog.log('debug', "has end time: " + str(has_end_time))

      #
      # This should never happen, so attempt to capture it.
      #
      if has_end_time and (has_ended and not has_started):
        raise Exception("Event can't end without starting!")

      #
      # Determines if the outage fits into the defined scopes.
      #
      within_future_scope = seconds_until_start < self.settings['scope_ahead']
      within_past_scope = abs(seconds_until_end) < self.settings['scope_past']
      self.hmdclog.log('debug', "within future scope: " + str(within_future_scope))
      self.hmdclog.log('debug', "within past scope: " + str(within_past_scope))

      #
      # Was previously cast as boolean.
      #
      resolved = outage["resolved"]
      self.hmdclog.log('debug', "resolved: " + str(resolved))

      #
      # Outage is in progress if it:
      #   o has already started
      #   o has not ended or doesn't have an end time
      #   o is not resolved yet
      #
      if (has_started and (not has_ended or not has_end_time)) and not resolved:
        sorted_outages['active'].append(outage)
        self.hmdclog.log('debug', "Added outage to \"active\" queue.")

      #
      # Outage is complete if it:
      #   o has started and ended
      #   o is resolved
      # ...but only display the completed outage if it falls in the
      # scope. NOTE: within_past_scope doesn't work for outages that
      # are missing a defined end time, so those events will not
      # display once they are marked "resolved" in the calendar.
      #
      elif ((has_started and has_ended) or resolved) and within_past_scope:
        sorted_outages['completed'].append(outage)
        self.hmdclog.log('debug', "Added outage to \"completed\" queue.")

      #
      # Outage is upcoming if it:
      #   o has not started
      #   o is not resolved
      # ...but only display the outage if it falls in the scope.
      #
      elif (not has_started and not resolved) and within_future_scope:
        sorted_outages['scheduled'].append(outage)
        self.hmdclog.log('debug', "Added outage to \"scheduled\" queue.")

      #
      # Outage does not meet any of the above three criteria.
      #
      else:
        self.hmdclog.log('debug', "Outage not added to any queue.")

      self.hmdclog.log('debug', "Done sorting outage #" + str(counter) + ".")

    return sorted_outages

  def within_grace_period(self, cache_file, timeout):
    """Makes the cacher resilient to OpenScholar outages by allowing for
    connections to fail for a specified amount of time before throwing an error.
    Uses the mtime of the cache file as the checking mechanism.

    Parameters:
      cache_file (string): Full path to the cache file.
      timeout (int): The grace period allowed, in seconds.

    Attributes:
      cache_mtime (int): Last modified time of the cache file.
      now (int): Current date and time.
      threshold (int): Demarkation time for being under/over the grace period.
    """

    if not os.path.isfile(cache_file):
      return True

    cache_mtime = int(os.path.getmtime(cache_file))
    now = int(time.time())
    threshold = cache_mtime + timeout

    now_formatted = self.format_date(now, "now")
    cache_mtime_formatted = self.format_date(cache_mtime, "cache_mtime")
    threshold_formatted = self.format_date(threshold, "threshold")

    self.hmdclog.log('debug', "Now: " + now_formatted)
    self.hmdclog.log('debug', "Last check time: " + cache_mtime_formatted)
    self.hmdclog.log('debug', "Grace period: " + str(timeout) + " seconds")
    self.hmdclog.log('debug', "Threshold: " + threshold_formatted)

    if threshold > now:
      return True
    else:
      return False

if __name__ == '__main__':
  cacher = OSCalendarCache("DEBUG", True, False)
  cacher.get_updates()
