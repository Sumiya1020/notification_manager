import frappe
from frappe.model.document import Document

class TierDiscount(Document):
    def validate(self):
        if self.discount_value <= 0:
            frappe.throw("Discount value must be greater than 0")
            
        # Verify loyalty tier exists in loyalty program
        if self.loyalty_tier:
            parent_rule = frappe.get_doc("Notification Rule", self.parent)
            if parent_rule.loyalty_program:
                loyalty_program = frappe.get_doc("Loyalty Program", parent_rule.loyalty_program)
                tier_exists = False
                for tier in loyalty_program.collection_rules:
                    if tier.name == self.loyalty_tier:
                        tier_exists = True
                        break
                        
                if not tier_exists:
                    frappe.throw(f"Loyalty tier {self.loyalty_tier} not found in loyalty program {parent_rule.loyalty_program}")