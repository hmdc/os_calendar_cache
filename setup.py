from distutils.core import setup

setup(author='Bradley Frank',
      author_email='bfrank@hmdc.harvard.edu',
      data_files=[
           ('/etc', ['conf/os_calendar_cache.conf']),
           ('/etc/cron.d', ['cron/HMDC_os_calendar_cache'])],
      description='Caches OpenScholar calendar feeds.',
      license='GPLv2',
      name='OSCalendarCache',
      packages=['os_calendar_cache'],
      requires=[
           'bs4',
           'ConfigParser',
           'datetime',
           'dateutil',
           'filecmp',
           'hashlib',
           'icalendar',
           'lxml',
           'os',
           'pytz',
           're',
           'shutil',
           'sys',
           'time',
           'urllib2'],
      scripts=['scripts/os_calendar_cache.py'],
      url='https://github.com/hmdc/os_calendar_cache',
      version='1.0',
)