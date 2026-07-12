import requests
from bs4 import BeautifulSoup
import datetime

def get_forexfactory_events(hours_ahead=6):
    """
    Return a list of dicts with keys: 'title', 'time', 'impact', 'currency'.
    'time' is a datetime object in UTC.
    Only returns events within the next `hours_ahead`.
    """
    url = "https://www.forexfactory.com/calendar"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
    except Exception:
        return []

    events = []
    today = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    cutoff = today + datetime.timedelta(hours=hours_ahead)

    for row in soup.select('tr.calendar_row'):
        try:
            # Extract date/time
            date_str = row.get('data-event-datetime', '')
            if not date_str:
                continue
            event_time = datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M')
            event_time = event_time.replace(tzinfo=datetime.timezone.utc)

            if event_time > cutoff:
                continue

            # Extract impact
            impact_cell = row.find('td', class_='calendar__impact')
            impact = 'low'
            if impact_cell:
                span = impact_cell.find('span')
                if span:
                    impact = span.get('title', 'low').lower()

            # Extract title
            title_cell = row.find('td', class_='calendar__event')
            title = title_cell.text.strip() if title_cell else ''

            # Extract currency
            currency_cell = row.find('td', class_='calendar__currency')
            currency = currency_cell.text.strip() if currency_cell else ''

            events.append({
                'title': title,
                'time': event_time,
                'impact': impact,
                'currency': currency,
            })
        except Exception:
            continue

    return events


def is_high_impact_near(events, minutes_before=30, minutes_after=30):
    """
    Returns True if any high‑impact event is within `minutes_before` / `after` of now.
    """
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    window_start = now - datetime.timedelta(minutes=minutes_before)
    window_end = now + datetime.timedelta(minutes=minutes_after)

    for event in events:
        if event['impact'] == 'high' and window_start <= event['time'] <= window_end:
            return True
    return False