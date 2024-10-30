import frappe
from frappe.model.document import Document

class NotificationLog(Document):
    def before_insert(self):
        # Add timestamp if not present
        if not self.creation:
            self.creation = frappe.utils.now()