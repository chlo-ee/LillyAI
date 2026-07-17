"""Regex-based detection of carrier tracking numbers in free text (email
subject/from/body). Pure stdlib, no project imports - used both by the
Email input module (to leave a hint for the LLM) and indirectly by
ParcelTracking's validate() when the model registers a parcel.
"""

import re

# DHL formats that are unambiguous enough to always look for.
DHL_ALWAYS_PATTERNS = [
    re.compile(r'\b00\d{18}\b'),
    re.compile(r'\bJJD\d{16,20}\b'),
    re.compile(r'\b[A-Z]{2}\d{9}DE\b'),
]
# Bare 12-digit DHL numbers are too easy to confuse with other IDs -
# only look for them if the text actually mentions DHL.
DHL_CONTEXT_PATTERN = re.compile(r'\b\d{12}\b')
DPD_PATTERN = re.compile(r'\b0\d{13}\b')
AMAZON_PATTERN = re.compile(r'\b\d{3}-\d{7}-\d{7}\b')

# Same patterns without \b, for fullmatch() validation of a number the
# LLM already extracted (carrier is explicit there, so context rules don't apply).
DHL_VALIDATE_PATTERNS = [
    re.compile(r'00\d{18}'),
    re.compile(r'JJD\d{16,20}'),
    re.compile(r'[A-Z]{2}\d{9}DE'),
    re.compile(r'\d{12}'),
]
DPD_VALIDATE_PATTERN = re.compile(r'0\d{13}')
AMAZON_VALIDATE_PATTERN = re.compile(r'\d{3}-\d{7}-\d{7}')


def scan(text):
    if not text:
        return []
    lower = text.lower()

    # (start, end, carrier, tracking_number) - collected before overlap/dedup filtering
    candidates = []
    for pattern in DHL_ALWAYS_PATTERNS:
        for match in pattern.finditer(text):
            candidates.append((match.start(), match.end(), 'DHL', match.group()))

    if 'dhl' in lower:
        for match in DHL_CONTEXT_PATTERN.finditer(text):
            candidates.append((match.start(), match.end(), 'DHL', match.group()))

    if 'dpd' in lower:
        for match in DPD_PATTERN.finditer(text):
            candidates.append((match.start(), match.end(), 'DPD', match.group()))

    if 'amazon' in lower:
        for match in AMAZON_PATTERN.finditer(text):
            candidates.append((match.start(), match.end(), 'Amazon', match.group()))

    # Longer/more specific matches first so a less specific pattern can't
    # steal a sub-span already claimed by a more specific one.
    candidates.sort(key=lambda c: (c[0], -(c[1] - c[0])))

    occupied = []
    hits = []
    seen = set()
    for start, end, carrier, tracking_number in candidates:
        if any(start < o_end and end > o_start for o_start, o_end in occupied):
            continue
        occupied.append((start, end))
        key = (carrier, tracking_number)
        if key in seen:
            continue
        seen.add(key)
        hits.append({'carrier': carrier, 'tracking_number': tracking_number})

    return hits


def validate(carrier, tracking_number):
    if carrier == 'DHL':
        return any(pattern.fullmatch(tracking_number) for pattern in DHL_VALIDATE_PATTERNS)
    if carrier == 'DPD':
        return bool(DPD_VALIDATE_PATTERN.fullmatch(tracking_number))
    if carrier == 'Amazon':
        return bool(AMAZON_VALIDATE_PATTERN.fullmatch(tracking_number))
    return False


def format_hint(hits):
    if not hits:
        return None
    parts = [f"{hit['carrier']} {hit['tracking_number']}" for hit in hits]
    return f"[System hint: possible parcel tracking numbers detected in this email: {', '.join(parts)}]"
