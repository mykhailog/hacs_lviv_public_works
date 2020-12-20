# This code based on FeedReader component
# https://github.com/home-assistant/core/blob/dev/homeassistant/components/feedreader/__init__.py

import requests
import re
import json
import pickle
import voluptuous as vol

from datetime import datetime, timedelta, date, time
from logging import getLogger
from os.path import exists
from threading import Lock
from bs4 import BeautifulSoup

from homeassistant.const import CONF_SCAN_INTERVAL, EVENT_HOMEASSISTANT_START
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import track_time_interval

_LOGGER = getLogger(__name__)
DEFAULT_SCAN_INTERVAL = timedelta(hours=3)

CONF_STREET='street'
CONF_HOUSE='house'
DOMAIN = "lviv_public_works"

EVENT_NEW_LVIV_PUBLIC_WORK = "lviv_public_works_event"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: {
            vol.Required(CONF_STREET): cv.string,
            vol.Optional(CONF_HOUSE, default=''): cv.string,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
            ): cv.time_period
        }
    },
    extra=vol.ALLOW_EXTRA,
)


def setup(hass, config):
    """Set up the component."""
    street = config.get(DOMAIN)[CONF_STREET]
    house = config.get(DOMAIN)[CONF_HOUSE]
    scan_interval = config.get(DOMAIN).get(CONF_SCAN_INTERVAL)
    data_file = hass.config.path(f"{DOMAIN}.pickle")
    storage = StoredData(data_file)
    street_resolver = StreetResolver()
    street_ids = street_resolver.resolve(street)
    if len(street_ids) != 1:
        _LOGGER.error(
                            "Failed to resolve street id for %s.",
                            street
                        )
        return False

    LvivPublicWorksManager(street_ids[0],house, scan_interval, hass, storage)
    return True

class LvivPublicWorksFetcher:
    def __init__(self, street_id, house):
        self.street_id = street_id
        self.house = house
        self.events = []

    def fetch(self):
        headers = {
            'authority': '1580.lviv.ua',
            'accept': '*/*',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36',
            'content-type': 'multipart/form-data; boundary=----WebKitFormBoundaryHass',
            'origin': 'https://1580.lviv.ua',
            'referer': 'https://1580.lviv.ua/perelik-vsi/',
            'accept-language': 'uk,en;q=0.9',
         }

        data_template = "from={from}&to={to}&streetid={street_id}&skyscraperid=&house={house}&street=&radio1580datetype=2&radio1580works=1"
        # format escaped date
        today = datetime.today().strftime("%Y/%m/%d").replace("/","%2F")
        tomorrow = (datetime.today() + timedelta(days=1)).strftime("%Y/%m/%d").replace("/","%2F")

        data_params = {'from':today, 'to':tomorrow, 'street_id':self.street_id or '','house':self.house or ''}
        data = data_template.format(**data_params)

        body = """
------WebKitFormBoundaryHass
Content-Disposition: form-data; name="data"

{data}
------WebKitFormBoundaryHass
Content-Disposition: form-data; name="rn"

0
------WebKitFormBoundaryHass
Content-Disposition: form-data; name="all"

1
------WebKitFormBoundaryHass
Content-Disposition: form-data; name="isFrame"


------WebKitFormBoundaryHass
Content-Disposition: form-data; name="hr"

1
------WebKitFormBoundaryHass
Content-Disposition: form-data; name="frameJeoId"

0
------WebKitFormBoundaryHass--
        """.format(data=data)

        response = requests.post('https://1580.lviv.ua/ajax/inform/informList.php', headers=headers, data=body)
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        for row in soup.find_all('div', class_="row animColor"):
          start_date = row.find('div',class_='StartDate')
          end_date = row.find('div',class_='EndDate') or row.find('div',class_='PlanDate')
          title = row.find('b').text.strip()
          content = row.find('div',class_='panel-heading animColor').text

          event = {
             'id': row['id'],
             'start_date': start_date.text.strip().replace("Початок","") if start_date else None,
             'end_date': end_date.text.strip().replace("Кінець","").replace("Заплановано","") if end_date else None,
             'title': title,
             'content': content.replace(title,'',1).strip()
             }
          events.append(event)
        self.events = events
        return True

class StreetResolver:
    def resolve(self,street_name):
        headers = {
            'authority': '1580.lviv.ua',
            'cache-control': 'max-age=0',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'referer': 'https://1580.lviv.ua/',
            'accept-language': 'uk,en;q=0.9',
          }

        response = requests.get('https://1580.lviv.ua/perelik-vsi/', headers=headers)
        streets_js = re.search('\$input\.typeahead\({source:\[(.*?)\]',response.text)
        # quick transform js dictionary to json
        streets = json.loads("[" + streets_js.group(1).replace("name:", '"name":').replace("id:", '"id":') + "]")
        resolved_ids = []

        for street in streets:
            if street_name in street['name']:
               resolved_ids.append(street['id'])
        return resolved_ids
class LvivPublicWorksManager:
    """Abstraction over LvivPublicWorksManager module."""

    def __init__(self, street_id, house, scan_interval, hass, storage):
        """Initialize the LvivPublicWorksManager object, poll as per scan interval."""
        self._street_id = street_id
        self._house = house
        self._scan_interval = scan_interval
        self._events_fetcher = None
        self._hass = hass
        self._storage = storage
        self._last_update_successful = False
        self._event_type = EVENT_NEW_LVIV_PUBLIC_WORK
        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, lambda _: self._update())
        self._init_regular_updates(hass)

    def _log_no_events(self):
        """Send no events log at debug level."""
        _LOGGER.debug("No new events to be published from 1580.lviv.ua")

    def _init_regular_updates(self, hass):
        """Schedule regular updates at the top of the clock."""
        track_time_interval(hass, lambda now: self._update(), self._scan_interval)

    @property
    def last_update_successful(self):
        """Return True if the last event update was successful."""
        return self._last_update_successful

    def _update(self):
        """Update the event list and publish new entries to the event bus."""
        _LOGGER.info("Fetching new events from 1580.lviv.ua")
        self._events_fetcher = LvivPublicWorksFetcher(self._street_id, self._house)

        if not self._events_fetcher.fetch():
            _LOGGER.error("Error fetching events from 1580.lviv.ua")
            self._last_update_successful = False
        else:
            if self._events_fetcher.events:
                _LOGGER.debug(
                    "%s event(s) available at 1580.lviv.ua",
                    len(self._events_fetcher.events)
                )
                self._publish_new_events()

            else:
                self._log_no_events()
            self._last_update_successful = True
        _LOGGER.info("Fetch events from 1580.lviv.ua completed")

    def _update_and_fire(self, event):
        self._storage.mark_published(event['id'],event['start_date'])
        self._hass.bus.fire(self._event_type, event)

    def _publish_new_events(self):
        """Publish new events to the event bus."""
        new_events = False
        for event in self._events_fetcher.events:
            if not self._storage.is_published(event['id']):
               new_entries = True
               self._update_and_fire(event)
        if not new_events:
            self._log_no_events()



class StoredData:
    """Abstraction over pickle data storage."""

    def __init__(self, data_file):
        """Initialize pickle data storage."""
        self._data_file = data_file
        self._lock = Lock()
        self._cache_outdated = True
        self._data = {}
        self._fetch_data()

    def _fetch_data(self):
        """Fetch data stored into pickle file."""
        if self._cache_outdated and exists(self._data_file):
            try:
                _LOGGER.debug("Fetching data from file %s", self._data_file)
                with self._lock, open(self._data_file, "rb") as myfile:
                    self._data = pickle.load(myfile) or {}
                    self._cache_outdated = False
            except:  # noqa: E722 pylint: disable=bare-except
                _LOGGER.error(
                    "Error loading data from pickled file %s", self._data_file
                )

    def is_published(self, event_id):
        """Return stored timestamp for given event id."""
        self._fetch_data()
        return self._data.get(event_id)

    def mark_published(self, event_id, published_at):
        """Update timestamp for given event id."""
        self._fetch_data()
        with self._lock, open(self._data_file, "wb") as myfile:
            self._data.update({event_id: published_at})
            _LOGGER.debug(
                "Overwriting 1580.lviv.ua message %s timestamp in storage file %s",
                event_id,
                self._data_file,
            )
            try:
                pickle.dump(self._data, myfile)
            except:  # noqa: E722 pylint: disable=bare-except
                _LOGGER.error("Error saving pickled data to %s", self._data_file)
        self._cache_outdated = True