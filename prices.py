"""
http://bitcoincharts.com/ prices python API
Manuel Araoz 2013
"""
from google.appengine.api import urlfetch
import logging

BASE_URL = "http://bitcoincharts.com/t/trades.csv?"

def get_url(symbol, start, end):
    url = BASE_URL + ("symbol=mtgox%s&start=%s&end=%s" % (symbol, start, end))
    return url


def get_price_avg(symbol, start, end):
    url = get_url(symbol, start, end)
    result = urlfetch.fetch(url)
    if result.status_code == 200:
        s = result.content.split("\n")
        suma = 0
        n = 0
        for line in s:
            if line:
                _, price, _ = tuple(line.split(","))
                suma += float(price)
                n += 1
        if n == 0:
            return -1
        print "%s %s/BTC is the %s-point average with a delta of %s" % (price, symbol, n, end-start)
        return float(suma)/n
    else:
        logging.error('There was an error contacting the bitcoincharts.com API')
        return None
    
MAX_TRIES = 5
def get_price(symbol, timestamp):
    timestamp = int(timestamp)
    delta = 60*1
    
    # dynamic range average fining
    for _ in xrange(MAX_TRIES):
        start = timestamp - delta
        end = timestamp + delta 
        price = get_price_avg(symbol, start, end)
        if not price: # network error
            return None
        if price > 0:
            return price
        delta *= 4
    return None
            




