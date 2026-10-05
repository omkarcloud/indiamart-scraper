"""Configuration for the Indiamart Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT             port the API listens on (default 8000)
    INDIAMART_PROXY  proxy URL, e.g. http://user:pass@host:port (default: none
                     — direct). IndiaMART allows about 15 requests a minute
                     per IP on each of its hosts and answers HTTP 429 above
                     that. Without a proxy the scraper waits the limit out and
                     retries, which is fine for light use. For volume, set a
                     ROTATING residential proxy: the first
                     INDIAMART_DIRECT_PER_MINUTE requests a minute still go out
                     directly and the overflow rides the proxy.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

INDIAMART_PROXY = os.environ.get("INDIAMART_PROXY") or None

# The transport only asks "is a proxy configured?" through this name.
INDIAMART_PROXY_COUNTRY = "custom" if INDIAMART_PROXY else None
INDIAMART_DIRECT_PER_MINUTE = 10    # own-IP requests a minute per host before the proxy takes over
INDIAMART_DIRECT_COOLDOWN = 90      # seconds a host stays on the proxy after a 429 on your own IP
INDIAMART_REQUESTS_PER_EXIT = 10    # reconnect to the proxy after this many requests (new exit on rotating proxies)
INDIAMART_MAX_ATTEMPTS = 4          # tries per upstream call


def indiamart_proxy():
    """The proxy URL for overflow requests (None = direct)."""
    return INDIAMART_PROXY
