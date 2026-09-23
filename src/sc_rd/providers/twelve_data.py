"""Small Twelve Data adapter. One explicit HTTPS GET, no redirects or retries."""
import http.client
import json
import os
import ssl
from urllib.parse import urlencode


class ProviderError(ValueError):
    """Sanitized public error; never include provider bodies, headers or URLs."""


def fetch_series(request):
    key = os.environ.get('TWELVE_DATA_API_KEY', '')
    if not key:
        raise ProviderError('MISSING_CREDENTIAL')
    params = {'symbol': request['provider_symbol'], 'exchange': request['exchange'],
              'interval': request['timeframe'], 'start_date': request['start'][:19],
              'end_date': request['end'][:19], 'timezone': 'UTC', 'order': 'asc',
              'outputsize': 5000, 'adjust': request['adjustment_policy']}
    connection = None
    try:
        connection = http.client.HTTPSConnection('api.twelvedata.com', timeout=30, context=ssl.create_default_context())
        connection.request('GET', '/time_series?' + urlencode(params), headers={'Authorization': 'apikey ' + key})
        response = connection.getresponse()
        if response.status != 200:
            raise ProviderError(f'HTTP_{response.status}')
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ProviderError('RESPONSE_TOO_LARGE')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get('status') != 'ok':
            code = payload.get('code') if isinstance(payload, dict) else None
            raise ProviderError(f'PROVIDER_{code}' if type(code) is int else 'INVALID_RESPONSE')
        return payload
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('NETWORK_OR_INVALID_RESPONSE') from None
    finally:
        if connection is not None:
            connection.close()
