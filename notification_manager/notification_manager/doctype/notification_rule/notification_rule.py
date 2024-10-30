import frappe
from frappe.model.document import Document

class NotificationRule(Document):
    def validate(self):
        if self.tier_discounts and not self.loyalty_program:
            frappe.throw("Please select a Loyalty Program if using tier discounts")
            
        if not self.tier_discounts and not self.discount_value:
            frappe.throw("Please specify either tier discounts or a default discount value")
            
        # Validate message template
        required_variables = ["{customer_name}", "{coupon_code}", "{discount_value}", "{validity_days}"]
        for var in required_variables:
            if var not in self.message_template:
                frappe.throw(f"Message template must include {var}")

    def before_save(self):
        # Ensure unique tier discounts
        if self.tier_discounts:
            tiers = {}
            for discount in self.tier_discounts:
                if discount.loyalty_tier in tiers:
                    frappe.throw(f"Duplicate tier {discount.loyalty_tier} found")
                tiers[discount.loyalty_tier] = discount.discount_value