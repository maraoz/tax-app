from google.appengine.ext import db

class WorkRequest(db.Model):
    identifier = db.StringProperty(required=True)
    email = db.StringProperty(required = True)
    export_format = db.StringProperty(required = True, choices=["xls", "pdf", "web"])
    symbol = db.StringProperty(required = True, choices=["USD", "EUR", "GBP"])
    
    addresses = db.StringListProperty()
    csv = db.TextProperty()
    csv_format = db.StringProperty()
    
    @classmethod
    def from_id(cls, identifier):
        return cls.all().filter("identifier =", identifier).get()
