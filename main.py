import os
import urllib
import json
import datetime
import random
from StringIO import StringIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch


import webapp2
import jinja2
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import blobstore
from google.appengine.api import urlfetch
from google.appengine.api import mail

from model import WorkRequest

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])


master_address = "1NwGkjiksHyJ5J8RYBGkFPZhSyGpki1Dv7"

_cost = 2000000  # 0.02 btc

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
        newaddress = result.content

        work = WorkRequest(identifier=newaddress, email=email)
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

        elif len(self.request.get("csv")) > 3:

            work.csv = self.request.get("csv")

        else:
            self.response.out.write("Error, nothing entered.")

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
        
        # FIXME for now no need to pay
        val = 123456789
        
        # output work
        output = ""
        if val >= _cost:
            if len(work.addresses) > 0:
                d = self.magic(work)

                # if isinstance(d, str) or isinstance(d, unicode):
                #    return self.response.out.write(d)

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
            else:
                self.print_csv_magic(work)
            
            self.response.out.write(output.replace("\n", "<br />"))
            
            buf = StringIO()
            doc = SimpleDocTemplate(buf)
            # doc.drawString(100,750,output)
            styles = getSampleStyleSheet()
            story = []
            for line in output.split("\n"):
                story.append(Paragraph(line, styles["Normal"]))
            doc.build(story)
            # doc.save()
    
            
            sender_address = "Taxapp <manuelaraoz@gmail.com>"
            subject = "Your taxapp report"
            body = """Please find attached your TaxMyBitcoin report.\n\n"""
            body += output
            mail.send_mail(sender_address, work.email, subject, body, attachments=[('output.pdf', buf.getvalue())])

        else:
            self.response.out.write("You haven't yet paid.")

    def print_csv_magic(self, data):

        self.response.out.write("Date,Transaction ID,#Conf,Wallet ID,Wallet Name,Total Credit (BTC),Total Debit (BTC),Fee (BTC),Comment,USD transacted,USD/BTC,Fee in USD\n")

        lines = data.csv.split("\n")
        # ignore header
        if "Total Credit" in lines[0]:
            del lines[0]

        totals = [[0, 0], [0, 0]]

        if len(lines) == 1:
            lines = data.csv.split("\\n")

        for line in lines:
            line = line.replace("\r", "").replace('"', "")
            if len(line.rstrip()) == 0:
                continue
            spl = line.split(",")

            try:
                time = datetime.datetime.strptime(spl[0], "%Y-%b-%d %I:%M%p").strftime("%s")
            except ValueError:
                return self.response.out.write("Invalid date stamp: %s" % line)

            try:
                g_in = float(spl[5].rstrip() or 0)
                g_out = float(spl[6].rstrip() or 0)
                fee = abs(float(spl[7].rstrip() or 0))
            except ValueError:
                return self.response.out.write("error: input/output values incorrect %s\n\n %s" % (line, lines))

            number = g_in + g_out
            usd_price = self.get_price_day(time)
            usd_fee = str(('%.2f' % (usd_price * fee)) or "")

            usd = usd_price * number

            if g_in > 0:
                totals[0][0] += g_in
            else:
                totals[0][1] += abs(g_out)
            if usd > 0:
                totals[1][0] += usd
            else:
                totals[1][1] += abs(usd)


            self.response.out.write(line + ",%.2f,%.2f,%s\n" % (usd, usd_price, usd_fee))

        self.response.out.write("Total BTC In,%f\n" % totals[0][0])
        self.response.out.write("Total BTC Out,%f\n" % totals[0][1])
        self.response.out.write("Total USD In,%f\n" % totals[1][0])
        self.response.out.write("Total USD Out,%f\n" % totals[1][1])
        self.response.out.write("\n")

    def magic(self, data):
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
                        exchange = self.get_price_day(date)
                        delta_usd = float('%.2f' % (exchange * delta_btc))
                        which_addr = self.which_is_it(json.dumps(tx), data.addresses)
                        # output[which_addr].append([date, delta_btc, delta_usd, exchange])
                        new_tx = {
                                   "date":date,
                                   "delta_btc": delta_btc,
                                   "delta_usd": delta_usd,
                                   "exchange" : exchange
                                   }
                        #self.response.out.write(str(new_tx)+"<br/>")
                        output[which_addr].append(new_tx)

                curr += 50
                if json.loads(res.content)['wallet']['n_tx'] < curr:
                    break

        return output

    def which_is_it(self, text, l):
        for i in l:
            if i in text:
                return i

    def get_price_day(self, timestamp):
        return datab[min(datab.keys(), key=lambda x:abs(x - int(timestamp)))]

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

datab = {1343692800: 9.244873049709, 1349222400: 12.835522979425, 1371340800: 99.925175984283, 1366761600: 152.068697926645, 1362182400: 33.870475107575, 1357603200: 13.720705290541, 1369785600: 130.374766294413, 1365206400: 142.158000062809, 1360627200: 25.088404193415, 1351468800: 10.650047190709, 1346889600: 10.935777345622, 1372809600: 83.176690253598, 1368230400: 115.54664107217, 1363651200: 55.38797958682, 1359072000: 16.663761610151, 1354492800: 12.567252214719, 1349913600: 12.025384714706, 1345334400: 9.086528172933, 1371254400: 100.452317791681, 1366675200: 134.629729861174, 1344643200: 11.501069794986, 1357516800: 13.505263060265, 1352937600: 11.076587946216, 1348358400: 12.004372230369, 1343779200: 9.425955215079, 1369699200: 127.977846820213, 1365120000: 139.217296079815, 1360540800: 24.129277454912, 1355961600: 13.534236491035, 1351382400: 10.569217758688, 1346803200: 10.752079307248, 1372723200: 90.030405812307, 1368144000: 118.030418336077, 1363564800: 48.983553130537, 1358985600: 17.750351834311, 1354406400: 12.561684448415, 1349827200: 12.024771331552, 1345248000: 11.872662901012, 1371168000: 100.637259228514, 1366588800: 123.233050022032, 1362009600: 32.694444246719, 1357430400: 13.460109303505, 1352851200: 10.945517762972, 1351123200: 11.028776090875, 1369353600: 129.847733459955, 1348272000: 12.223376499005, 1374192000: 89.444840099099, 1369612800: 129.340985766225, 1365033600: 131.613242136085, 1360454400: 23.42026731801, 1355875200: 13.40381168638, 1351296000: 10.377047741744, 1346716800: 10.304464611393, 1372636800: 91.24379124339, 1368057600: 111.661234736234, 1363478400: 47.399944453793, 1358899200: 17.216813444851, 1354320000: 12.578640338842, 1349740800: 11.967272286991, 1345161600: 13.25851067674, 1371081600: 105.242496709819, 1366502400: 121.497825586259, 1361923200: 31.217674561077, 1357344000: 13.452109199252, 1352764800: 11.002160184143, 1348185600: 12.269481646018, 1343606400: 8.952839520418, 1370044800: 128.407386937459, 1374105600: 90.939563266303, 1369526400: 134.016872786061, 1364947200: 127.893572623089, 1360368000: 23.235351511166, 1355788800: 13.235147398629, 1351209600: 10.309811620016, 1346630400: 10.349460905092, 1372550400: 96.843565212209, 1367971200: 113.334665328235, 1363392000: 46.864015212137, 1354233600: 12.55887719185, 1349654400: 11.255332258282, 1345075200: 13.226291000029, 1370995200: 109.266555195466, 1366416000: 124.024014600484, 1361836800: 31.01169314452, 1357257600: 13.423030603879, 1352678400: 10.992137412428, 1348099200: 12.480832791413, 1343520000: 8.768353362849, 1374019200: 98.44459359427, 1369440000: 130.87355679399, 1366848000: 143.070672095698, 1355616000: 13.350992337688, 1364860800: 107.607635599803, 1360281600: 22.418912516137, 1355702400: 13.186800338964, 1346544000: 10.054879748881, 1372464000: 96.691951221566, 1367884800: 106.705730501845, 1363305600: 47.032080137469, 1354147200: 12.433441284114, 1349568000: 12.010526343351, 1344988800: 12.609440783608, 1370908800: 106.984034667166, 1366329600: 119.430373561819, 1361750400: 30.071025059931, 1357171200: 13.356394124545, 1352592000: 10.807363100269, 1348012800: 12.405833668811, 1343433600: 8.857606973171, 1373932800: 98.154141872955, 1364774400: 100.035795877489, 1360195200: 21.605732761994, 1348444800: 12.123963338022, 1351036800: 11.676361456085, 1346457600: 10.000650489079, 1372377600: 96.807755292358, 1367798400: 117.324246208511, 1363219200: 47.313634694516, 1358640000: 15.720646174555, 1354060800: 12.281620038137, 1349481600: 12.584927465945, 1344902400: 12.093696092879, 1370822400: 105.490900745905, 1366243200: 97.380573940152, 1361664000: 29.781413972196, 1357084800: 13.311000514192, 1352505600: 10.848361338266, 1347926400: 12.064438585858, 1343347200: 8.893585007835, 1373846400: 98.651616355008, 1369267200: 125.325430631358, 1364688000: 92.699003526208, 1360108800: 21.088759913742, 1355529600: 13.542010705593, 1350950400: 11.72715008556, 1346371200: 10.184972570421, 1343865600: 10.133880237154, 1372291200: 102.07989865413, 1367712000: 113.496283188556, 1363132800: 46.414136430471, 1358553600: 15.4577996887, 1353974400: 12.101092821618, 1349395200: 12.746223785163, 1344816000: 11.789615202121, 1366156800: 85.268988650254, 1361577600: 29.051142002672, 1356998400: 13.3379053055, 1352419200: 10.863284661979, 1347840000: 11.899013744054, 1343260800: 8.770734812963, 1373760000: 95.876058357108, 1369180800: 122.999048983227, 1364601600: 91.723690166077, 1360022400: 20.571705861073, 1355443200: 13.558483676559, 1350864000: 11.699006928329, 1346284800: 10.762065789971, 1372204800: 104.111522916809, 1361404800: 29.681700190011, 1367625600: 106.674330895893, 1363046400: 43.69791992655, 1358467200: 15.68082813834, 1353888000: 12.356051559148, 1349308800: 12.882047549939, 1344729600: 11.637494266894, 1370649600: 108.807818292995, 1366070400: 65.332171452405, 1356912000: 13.47519889075, 1352332800: 10.919748156938, 1347753600: 11.876794904352, 1343174400: 8.588932189846, 1373673600: 93.008862060436, 1369094400: 122.282303719922, 1364515200: 88.777352515848, 1359936000: 20.424890061282, 1355356800: 13.698868110626, 1350777600: 11.677212017164, 1346198400: 10.842728086754, 1372118400: 104.145370631992, 1367539200: 91.295597338099, 1362960000: 47.615507918227, 1358380800: 15.165583465164, 1345766400: 10.265052215258, 1353024000: 11.4916021955, 1370563200: 112.076390208391, 1365984000: 87.067542993519, 1356825600: 13.454140477209, 1347667200: 11.707589589954, 1373587200: 96.425536083916, 1369008000: 122.311435053418, 1364428800: 87.412870807034, 1359849600: 20.261755484938, 1355270400: 13.599482549907, 1350691200: 11.718784592718, 1346112000: 10.900486065026, 1372032000: 103.291079944891, 1367452800: 106.488650406564, 1362873600: 46.83643500686, 1358294400: 14.515562704555, 1353715200: 12.368615595653, 1349136000: 12.630053046484, 1344556800: 11.40942007971, 1352246400: 10.981165033997, 1370476800: 119.67742216095, 1365897600: 97.408670886849, 1361318400: 29.472187048329, 1356739200: 13.488869900635, 1352160000: 10.798765602605, 1347580800: 11.5758622349, 1373500800: 87.517984261338, 1368921600: 121.867256309598, 1364342400: 84.86816591378, 1359763200: 19.469478935614, 1355184000: 13.501863342866, 1350604800: 11.76319546979, 1346025600: 11.179195023784, 1371945600: 107.485870356258, 1367366400: 121.051623478786, 1362787200: 45.436747753002, 1358208000: 14.201718094782, 1353628800: 12.30346442448, 1349049600: 12.39064920835, 1344470400: 11.325143846554, 1358726400: 16.384584981929, 1362096000: 34.240332876155, 1370390400: 121.462958688055, 1365811200: 110.207968886882, 1361232000: 28.185532756754, 1356652800: 13.44741450376, 1352073600: 10.729355959173, 1347494400: 11.344322130053, 1373414400: 82.395135743196, 1368835200: 123.819007727659, 1364256000: 77.246938621035, 1359676800: 20.726592214106, 1355097600: 13.424552479238, 1350518400: 11.875943608185, 1345939200: 10.549293030229, 1371859200: 108.530657874039, 1367280000: 139.868098186599, 1362700800: 43.159723966787, 1358121600: 14.256112914108, 1353542400: 12.068047773948, 1348963200: 12.376591658716, 1344384000: 11.035592045625, 1370304000: 121.070812372399, 1365724800: 85.568427603757, 1361145600: 26.756962457958, 1370736000: 98.010312144504, 1356566400: 13.384679406424, 1351987200: 10.672123743968, 1347408000: 11.206318612422, 1373328000: 75.645653093624, 1368748800: 121.430507665276, 1364169600: 74.251997838872, 1359590400: 20.581542731679, 1355011200: 13.230409043552, 1350432000: 11.878339936851, 1345852800: 10.448968323689, 1371772800: 111.33778495623, 1367193600: 142.249560867888, 1362614400: 40.934834912059, 1358035200: 14.107942308029, 1353456000: 11.717864262784, 1348876800: 12.396647215092, 1344297600: 10.850889080725, 1370217600: 119.00812597703, 1365638400: 158.926033099863, 1361059200: 26.396105037165, 1356480000: 13.342635535602, 1351900800: 10.538798439315, 1359244800: 17.653653018277, 1361491200: 30.460943673167, 1373241600: 76.959430127027, 1368662400: 115.43816692192, 1364083200: 68.92198995152, 1359504000: 19.48001230239, 1354924800: 13.463782727327, 1350345600: 11.793727803754, 1371686400: 111.261089389359, 1367107200: 133.168512263334, 1362528000: 45.175131743108, 1357948800: 14.167135093566, 1353369600: 11.693208620475, 1348790400: 12.350112510018, 1344211200: 10.899005412359, 1370131200: 121.963997480411, 1365552000: 184.648263198272, 1360972800: 27.164364463065, 1356393600: 13.312275768959, 1351814400: 10.576067422475, 1347235200: 11.044814646651, 1356048000: 13.523561429392, 1373155200: 70.770567432439, 1368576000: 110.247581729712, 1363996800: 62.669190665713, 1359417600: 19.16921785794, 1354838400: 13.345498368625, 1350259200: 11.720037002845, 1345680000: 9.997428066455, 1371600000: 107.870548386308, 1367020800: 131.179266080909, 1362441600: 39.34860518747, 1357862400: 14.113606754064, 1353283200: 11.717664978487, 1348704000: 12.317235851068, 1344124800: 10.625164772506, 1365465600: 214.673543657153, 1360886400: 26.994895051377, 1356307200: 13.378454288045, 1351728000: 10.927413463353, 1347148800: 11.04524863496, 1373068800: 70.257336902986, 1368489600: 114.849292686087, 1363910400: 70.646134643973, 1347321600: 11.110993962623, 1358812800: 17.152846069103, 1359331200: 18.339198470491, 1354752000: 13.382787363942, 1350172800: 11.844597517294, 1345593600: 9.857943717841, 1371513600: 107.39823340189, 1366934400: 132.24845153032, 1362355200: 35.470916228339, 1357776000: 14.047016964457, 1353196800: 11.712980198122, 1348617600: 12.233018624317, 1344038400: 10.998659447143, 1369958400: 128.149868562656, 1365379200: 181.493002536983, 1360800000: 25.459012325592, 1356220800: 13.218909381488, 1351641600: 11.023401424225, 1347062400: 10.976971684763, 1372982400: 71.109276172512, 1368403200: 117.020211848167, 1363824000: 69.072774825047, 1354665600: 13.281323751151, 1350086400: 11.960392047041, 1353801600: 12.487232882601, 1345507200: 10.026543773124, 1371427200: 100.929002996644, 1362268800: 34.131291795735, 1357689600: 13.744915740916, 1353110400: 11.674126135331, 1348531200: 12.114524610707, 1343952000: 10.732527201927, 1369872000: 129.405396439238, 1365292800: 154.255147971604, 1360713600: 25.477820200393, 1356134400: 13.424773006547, 1351555200: 10.75355056047, 1346976000: 11.100481530432, 1372896000: 78.286106677905, 1368316800: 114.600631914032, 1363737600: 62.022693124867, 1359158400: 17.151792704986, 1354579200: 13.025991518454, 1350000000: 12.049501159759, 1345420800: 9.532606044587}

app = webapp2.WSGIApplication([
    ('/', TaxHandler),
    ('/([^/]+)?', RetrieveTaxHandler)
], debug=False)
