"""Per-carrier HTTP clients for ParcelTracking. Each carrier has its own quirks
(auth, response shape, what counts as an error vs. a normal "not found yet"
state) so they are kept in one place, separate from the module's routing/
persistence logic.
"""

import requests

POLLABLE_CARRIERS = ('DHL', 'DPD')


class CarrierError(Exception):
    """Raised when a carrier lookup fails (network, HTTP, auth, unparseable response)."""


def poll(carrier, tracking_number, config):
    if carrier == 'DHL':
        return _poll_dhl(tracking_number, config)
    if carrier == 'DPD':
        return _poll_dpd(tracking_number)
    raise CarrierError(f"Carrier '{carrier}' cannot be polled")


def _poll_dhl(tracking_number, config):
    api_key = config.get('dhl_api_key')
    if not api_key:
        raise CarrierError('No DHL API key configured (dhl_api_key)')

    # timeout: a stalled DHL API must never hang the (synchronous) event loop.
    try:
        response = requests.get(
            'https://api-eu.dhl.com/track/shipments',
            params={'trackingNumber': tracking_number},
            headers={'DHL-API-Key': api_key, 'Accept': 'application/json'},
            timeout=15,
        )
    except requests.exceptions.Timeout:
        raise CarrierError('DHL tracking request timed out')
    except requests.exceptions.ConnectionError:
        raise CarrierError('Could not connect to the DHL tracking API')
    except requests.exceptions.RequestException as error:
        raise CarrierError(f'DHL tracking request failed: {error}')

    if response.status_code == 404:
        # Normal right after the shipping mail arrives - DHL hasn't picked up
        # the shipment yet. Not an error.
        return {'status': 'Not found in the DHL system yet', 'delivered': False}
    if response.status_code in (401, 403):
        raise CarrierError('DHL API key is invalid or not authorized')
    if response.status_code == 429:
        raise CarrierError('DHL tracking API rate limit exceeded')
    if response.status_code != 200:
        raise CarrierError(f'DHL tracking API returned HTTP {response.status_code}')

    try:
        data = response.json()
    except ValueError:
        raise CarrierError('DHL tracking API returned unparseable JSON')

    shipments = data.get('shipments')
    if not shipments:
        raise CarrierError('DHL tracking API returned no shipment data')

    try:
        shipment = shipments[0]
        status = shipment.get('status', {}) or {}
    except (AttributeError, IndexError, TypeError):
        raise CarrierError('DHL tracking API returned an unexpected shipment shape')

    status_code = status.get('statusCode')
    delivered = status_code == 'delivered'

    description = status.get('description') or status.get('status')
    location = None
    address = status.get('location', {}).get('address', {}) if isinstance(status.get('location'), dict) else {}
    if isinstance(address, dict):
        location = address.get('addressLocality')
    timestamp = status.get('timestamp')

    if not description and location is None and timestamp is None:
        raise CarrierError('DHL tracking API response had no usable status information')

    bits = description or 'Status unknown'
    if location:
        bits += f' — {location}'
    if timestamp:
        bits += f' ({timestamp})'

    return {'status': bits, 'delivered': delivered}


def _poll_dpd(tracking_number):
    # Unofficial endpoint backing tracking.dpd.de - not a documented/stable
    # API, so every assumption about its shape is guarded and any surprise
    # becomes a CarrierError rather than an unhandled exception.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    }

    try:
        response = requests.get(
            f'https://tracking.dpd.de/rest/plc/en_US/{tracking_number}',
            headers=headers,
            timeout=15,
        )
    except requests.exceptions.Timeout:
        raise CarrierError('DPD tracking request timed out')
    except requests.exceptions.ConnectionError:
        raise CarrierError('Could not connect to the DPD tracking API')
    except requests.exceptions.RequestException as error:
        raise CarrierError(f'DPD tracking request failed: {error}')

    if response.status_code != 200:
        raise CarrierError(f'DPD tracking API returned HTTP {response.status_code}')

    try:
        data = response.json()
    except ValueError:
        raise CarrierError('DPD tracking API returned unparseable JSON')

    try:
        status_info = data['parcellifecycleResponse']['parcelLifeCycleData']['statusInfo']
        if not status_info:
            raise CarrierError('DPD does not know this parcel (yet)')

        current = None
        for entry in status_info:
            if entry.get('isCurrentStatus'):
                current = entry
                break
        if current is None:
            for entry in status_info:
                if entry.get('statusHasBeenReached'):
                    current = entry
        if current is None:
            current = status_info[-1]

        status_value = current.get('status')
        delivered = status_value == 'DELIVERED'

        label = current.get('label')

        description = current.get('description')
        if isinstance(description, dict):
            content = description.get('content')
            if isinstance(content, list):
                description = ' '.join(str(part) for part in content if part)
            else:
                description = str(content) if content else None
        elif description is not None:
            description = str(description)

        date = current.get('date') or current.get('dateTime')

        bits = label or description or status_value or 'Status unknown'
        if description and description != bits:
            bits += f' — {description}'
        if date:
            bits += f' ({date})'
    except CarrierError:
        raise
    except (KeyError, IndexError, TypeError, ValueError):
        raise CarrierError('DPD tracking API returned an unexpected response format')

    return {'status': bits, 'delivered': delivered}
