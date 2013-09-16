import os
import urllib
import json
import random
import csv
from StringIO import StringIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import xlwt
import datetime
import time
ezxf = xlwt.easyxf


import webapp2
import jinja2
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import blobstore
from google.appengine.api import urlfetch
from google.appengine.api import mail

from model import WorkRequest
from prices import get_price


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])


master_address = "1NwGkjiksHyJ5J8RYBGkFPZhSyGpki1Dv7"

_cost = 2000000  # 0.02 btc


class BootstrapHandler(webapp2.RequestHandler):
    def get(self):
        now = datetime.datetime.now()
        timestamp = time.mktime(now.timetuple())
        self.response.out.write(get_price("USD", timestamp))

class TaxHandler(webapp2.RequestHandler):
    def get(self):
        self.response.out.write(JINJA_ENVIRONMENT.get_template('main.html').render({}))

    def post(self):
        url = 'http://btc-fork-api.appspot.com/new?cases={"%s":"default"}' % master_address

        result = urlfetch.fetch(url)

        if result.status_code != 200:
            self.response.out.write("ERROR: Cannot create new address.")
            return
        
        email = self.request.get("email")
        export_format = self.request.get("export_format")
        symbol = self.request.get("symbol")
        newaddress = result.content

        work = WorkRequest(identifier=newaddress, email=email, export_format=export_format, symbol=symbol)
        work.addresses = []
        work.csv = ""

        l = self.request.get("addresses")

        if len(l) > 3:
            if l.count(",") > 0:
                l = l.split(",")
            elif l.count("\n") > 0:
                l = l.replace("\r", "").split("\n")
            else:
                l = [l]

            work.addresses = l

            if len(l) > 50:
                self.response.out.write("Error, too many addresses. Please split up into multiple requests.")
                return

        else:
            csv = self.request.get("file")
            if len(csv) > 3:
                work.csv = csv
                work.csv_format = self.request.get("csv_format")
            else:
                self.response.out.write("Error, nothing entered.")
                return

        work.identifier = work.identifier

        work.put()

        if len(l) == 1:
            self.response.out.write("Successful! Check your results <a href='/%s'> here</a>." % work.identifier)
        else:
            self.response.out.write("Successful! Please send 0.02 BTC to <br/>%s<br/> and then once the network has received your payment, check your results <a href='/%s'> here</a>." % (work.identifier, work.identifier))

class RetrieveTaxHandler(webapp2.RequestHandler):
    def get(self, identifier):

        work = WorkRequest.from_id(identifier)

        if not (work and work.identifier):
            return self.response.out.write("Invalid identifier.")

        # checked if fee was payed
        if len(work.addresses) != 1:

            a_url = "http://blockchain.info/q/getreceivedbyaddress/%s" % work.identifier
            confirm = "?confirmations=0"

            res = urlfetch.fetch(a_url + confirm)
            if res.status_code != 200:
                return self.response.out.write("ERROR: Cannot get value.")

            try:
                val = int(res.content)
            except ValueError:
                return self.response.out.write("ERROR: Address isn't correct.")
        else:
            val = 12312893012839012839120
        
        # FIXME for now no need to pay, to test
        val = 123456789
        
        # output work
        output = ""
        if val >= _cost:
            d = []
            if len(work.addresses) > 0:
                d = self.magic(work, work.symbol)
            else:
                d = self.csv_magic(work, work.symbol)

            if isinstance(d, str) or isinstance(d, unicode):
                return self.response.out.write(d)

            for addr in d.keys():
                output += addr + "\n"
                output += "Date,BTC,USD value at time of payment,USD exchange rate at time of payment\n"
                btc_in, btc_out, usd_in, usd_out = 0, 0, 0, 0
                for tx in d[addr]:
                    if tx["delta_btc"] > 0:
                        btc_in += tx["delta_btc"]
                    else:
                        btc_out += abs(tx["delta_btc"])
                    if tx["delta_usd"] > 0:
                        usd_in += tx["delta_usd"]
                    else:
                        usd_out += abs(tx["delta_usd"])
                    output += datetime.datetime.fromtimestamp(int(tx["date"])).strftime('%Y-%b-%d %I:%M%p') + ","
                    output += str(tx["delta_btc"]) + "," 
                    output += str(tx["delta_usd"]) + "," 
                    output += ("%.2f" % tx["exchange"]) + "\n"

                output += "Total BTC In,%f\n" % btc_in
                output += "Total BTC Out,%f\n" % btc_out
                output += "Total USD In,%f\n" % usd_in
                output += "Total USD Out,%f\n" % usd_out
                output += "\n"
            
            self.response.out.write(output.replace("\n", "<br />"))
            buf = StringIO()
            fmt = work.export_format
            
            if fmt == "web":
                return
            
            if fmt == "pdf":
                doc = SimpleDocTemplate(buf)
                styles = getSampleStyleSheet()
                story = []
                for line in output.split("\n"):
                    story.append(Paragraph(line, styles["Normal"]))
                doc.build(story)
            if fmt == "xls":
                book = xlwt.Workbook()
                sheet = book.add_sheet("Tax app report")
                sheet.set_panes_frozen(True)
                sheet.set_remove_splits(True)
                for rowx, line in enumerate(output.split("\n")):
                    for colx, value in enumerate(line.split(",")):
                        sheet.write(rowx, colx, value)
                book.save(buf)
    
            
            
            sender_address = "Taxapp <manuelaraoz@gmail.com>"
            subject = "Your taxapp report"
            body = """Please find attached your TaxMyBitcoin report.\n\n"""
            body += output
            mail.send_mail(sender_address, work.email, subject, body, attachments=[('output.' + fmt, buf.getvalue())])

        else:
            self.response.out.write("You haven't yet paid.")

    def csv_magic(self, data, symbol):
        output = {}
        lines = data.csv.split("\n")
        
        electrum_balance = None

        # ignore headers
        if data.csv_format in ["bitcoin-qt", "electrum" ]:
            del lines[0]
        elif data.csv_format == "armory":
            while not "Fee (wallet paid)" in lines[0]:
                del lines[0]
            del lines[0]

        for line_n, spl in enumerate(csv.reader(lines, skipinitialspace=True)):
            if len(spl) == 0:
                continue
            line = ",".join(spl)
            
            # check CSV format is OK
            if data.csv_format == "bitcoin-qt":
                if len(spl) != 7:
                    return "Invalid bitcoin-qt CSV format: %s values at line %s" % (len(spl), line_n)
            elif data.csv_format == "armory":
                if len(spl) != 9:
                    return "Invalid Armory CSV format: %s values at line %s" % (len(spl), line_n)
            elif data.csv_format == "electrum":
                # transaction_hash,label,confirmations,value,fee,balance,timestamp
                if len(spl) != 7:
                    return "Invalid Electrum CSV format: %s values at line %s" % (len(spl), line_n)
                
            # extract important values
            if data.csv_format == "bitcoin-qt":
                try:
                    qt_date = "%Y-%m-%dT%H:%M:%S" # 2013-08-13T22:35:50
                    date_str = spl[1]
                    date = datetime.datetime.strptime(date_str, qt_date)
                    date = time.mktime(date.timetuple())
                except ValueError, e:
                    return "Invalid date stamp: %s - %s - %s" % (datetime.datetime.now().strftime(qt_date), date_str, e)
                try:
                    delta_btc = float(spl[5].rstrip() or 0)
                except ValueError:
                    return "error: input/output values incorrect %s" % (line)
                addr = "Bitcoin-qt wallet"
                
            elif data.csv_format == "armory":
                try:
                    armory_date = "%Y-%b-%d %I:%M%p" # 2013-Aug-13 09:46am
                    date_str = spl[0]
                    date = datetime.datetime.strptime(date_str, armory_date)
                    date = time.mktime(date.timetuple())
                except ValueError, e:
                    return "Invalid date stamp: %s - %s - %s" % (datetime.datetime.now().strftime(armory_date), date_str, e)
                try:
                    delta_btc = float(spl[5].rstrip() or 0) + float(spl[6].rstrip() or 0) + float(spl[7].rstrip() or 0) 
                except ValueError:
                    return "error: input/output values incorrect %s" % (line)
                addr = spl[4]
                
            elif data.csv_format == "electrum":
                try:
                    electrum_date = "%Y-%m-%d %H:%M" # 2013-08-20 15:43
                    date_str = spl[6]
                    date = datetime.datetime.strptime(date_str, electrum_date)
                    date = time.mktime(date.timetuple())
                except ValueError, e:
                    return "Invalid date stamp: %s - %s - %s" % (datetime.datetime.now().strftime(electrum_date), date_str, e)
                try:
                    updated_balance = float(spl[5].rstrip() or 0)
                    if not electrum_balance:
                        delta_btc = updated_balance
                    else: 
                        delta_btc = updated_balance - electrum_balance
                    electrum_balance = updated_balance  
                except ValueError:
                    return "error: input/output values incorrect %s" % (line)
                addr = "electrum"

            
            
            exchange = get_price(symbol, date)
            if not exchange:
                            return "ERROR: Cannot connect to bitcoincharts.com. %s - %s" % (symbol, date)
            delta_usd = float('%.2f' % (exchange * delta_btc))
            new_tx = {
               "date":date,
               "delta_btc": delta_btc,
               "delta_usd": delta_usd,
               "exchange" : exchange
           }
            # self.response.out.write(str(new_tx) + "<br/>")
            l = output.get(addr, [])
            l.append(new_tx)
            output[addr] = l
            
        return output
            

    def magic(self, data, symbol):
        output = {}
        if len(data.addresses) != 0:
            for addr in data.addresses:
                output[addr] = []

            curr = 0
            while curr < 1000:

                url = "https://blockchain.info/multiaddr?active=%s&offset=%d" % ("|".join(data.addresses), curr)
                res = urlfetch.fetch(url)
                if res.status_code != 200:
                    return "ERROR: Cannot connect to blockchain.info. %s \n %s" % (res.content or "", url)

                txs = json.loads(res.content)["txs"]

                for tx in txs:
                    for addr in data.addresses:
                        delta_btc = self.get_total_in(tx, addr) * 0.00000001
                        if delta_btc == 0:
                            continue

                        if "time" in tx:
                            date = tx["time"]
                        else:
                            date = 99999999999
                        exchange = get_price(symbol, date)
                        if not exchange:
                            return "ERROR: Cannot connect to bitcoincharts.com. %s - %s" % (symbol, date)
                        delta_usd = float('%.2f' % (exchange * delta_btc))
                        which_addr = self.which_is_it(json.dumps(tx), data.addresses)
                        new_tx = {
                                   "date":date,
                                   "delta_btc": delta_btc,
                                   "delta_usd": delta_usd,
                                   "exchange" : exchange
                                   }
                        output[which_addr].append(new_tx)

                curr += 50
                if json.loads(res.content)['wallet']['n_tx'] < curr:
                    break

        return output

    def which_is_it(self, text, l):
        for i in l:
            if i in text:
                return i

    def get_total_in(self, d, addr):
        total_in = 0
        total_out = 0
        for t in d['inputs']:
            if t['prev_out']['addr'] == addr:
                total_out += t['prev_out']['value']
        for t in d['out']:
            if t['addr'] == addr:
                total_in += t['value']

        return total_in - total_out

app = webapp2.WSGIApplication([
    ('/', TaxHandler),
    ('/api/bootstrap', BootstrapHandler),
    ('/([^/]+)?', RetrieveTaxHandler)
], debug=True)
