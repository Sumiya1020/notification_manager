import frappe
from frappe import _
from frappe.utils import today, add_days, getdate
from frappe.core.doctype.sms_settings.sms_settings import send_sms

class NotificationManager:
    def __init__(self):
        self.sms_settings = frappe.get_doc("SMS Settings")
        self.load_rules()

    def send_notification(self, customer, event_type):
        """Send notification based on event type"""
        if not customer.mobile_no:
            self.log_notification(customer, event_type, "Failed", "No mobile number")
            return False

        rule = self.get_rule(event_type)
        if not rule:
            self.log_notification(customer, event_type, "Failed", "No rule found")
            return False

        try:
            # Prepare message
            message = rule.message_template

            # Send SMS
            send_sms(
                receiver_list=[customer.mobile_no],
                msg=message
                # sender_name=self.sms_settings.sms_sender_name
            )

            # Log success
            self.log_notification(
                customer, event_type, "Success",
                f"Coupon: ",
                None,
                loyalty_tier
            )
            return True

        except Exception as e:
            self.log_notification(customer, event_type, "Failed", str(e))
            
            frappe.log_error(
                title='Error occured in notification send.',
                message=f"""
                Method: {'send_notification' or 'Not Specified'}
                Error: {e}
                """,
                reference_doctype="Notification Rule"
            )

            return False
        
    
    def send_tier_notification(self, customer, event_type):
        """Send notification with tier-specific discount values"""
        if not customer.mobile_no:
            self.log_notification(customer, event_type, "Failed", "No mobile number")
            return False

        rule = self.get_rule(event_type)
        if not rule:
            self.log_notification(customer, event_type, "Failed", "No rule found")
            return False

        try:
            # Get customer's current tier
            customer_tier = customer.loyalty_program_tier
            
            # Find matching tier discount
            tier_discount = None
            for td in rule.tier_discounts:
                if td.tier_name == customer_tier:
                    tier_discount = td
                    break
            
            # Use default discount value if no tier-specific discount found
            discount_value = tier_discount.discount_value if tier_discount else rule.discount_value
            
            # Prepare message by replacing placeholders
            message = rule.message_template.replace(
                "{discount_value}", str(discount_value)
            ).replace(
                "{customer_name}", customer.customer_name
            ).replace(
                "{validity_days}", str(rule.validity_days)
            ).replace(
                "{loyalty_tier}", customer_tier or "Classic"
            )

            # Send SMS
            send_sms(
                receiver_list=[customer.mobile_no],
                msg=message
            )

            # Log success
            self.log_notification(
                customer, 
                event_type, 
                "Success",
                f"Notification sent with discount value: {discount_value}",
                None,
                customer_tier
            )
            return True

        except Exception as e:
            self.log_notification(customer, event_type, "Failed", str(e))
            
            frappe.log_error(
                title='Error occurred in tier notification send.',
                message=f"""
                Method: send_tier_notification
                Error: {e}
                Customer: {customer.name}
                Event Type: {event_type}
                """,
                reference_doctype="Notification Rule"
            )
            return False


    def load_rules(self):
        """Load all active notification rules"""
        self.rules = frappe.get_all(
            "Notification Rule",
            filters={"enabled": 1},
            fields=["*"]
        )

    def get_loyalty_tier_discount(self, customer, rule):
        customer_doc = frappe.get_doc("Customer", customer)
        if not customer_doc.loyalty_program:
            return None
            
        loyalty_program = frappe.get_doc("Loyalty Program", customer_doc.loyalty_program)
        customer_points = 0
        
        # Get the tier discount settings from the notification rule
        tier_discounts = {d.tier_name: d.discount_value for d in rule.tier_discounts}
        
        # Find the customer's current tier based on points
        current_tier = None
        for tier in loyalty_program.tiers:
            if customer_points >= tier.min_point:
                if tier.name in tier_discounts:
                    current_tier = tier.name
                    
        return tier_discounts.get(current_tier)

    def create_coupon(self, customer, rule):
        """Create coupon based on notification rule"""
        discount_value = 0
        
        coupon = frappe.get_doc({
            "doctype": "Coupon Code",
            "coupon_name": f"{rule.event_type[:3].upper()}{customer.name[:5]}{today().replace('-', '')}",
            "coupon_type": "Gift Card",
            "discount_percentage": discount_value if rule.discount_type == "Percentage" else 0,
            "discount_amount": discount_value if rule.discount_type == "Amount" else 0,
            "valid_from": today(),
            "valid_upto": add_days(today(), rule.validity_days),
            "customer": customer.name,
            "maximum_use": 1,
            "pricing_rule": "PRLE-0005"
        })
        coupon.insert(ignore_permissions=True)
        return coupon

    def get_customer_tier(self, customer):
        """Get customer's current loyalty tier name"""
        if not customer.loyalty_program:
            return "Classic"

        loyalty_program = frappe.get_doc("Loyalty Program", customer.loyalty_program)
        points = frappe.db.sql("""
            SELECT sum(loyalty_points) as points
            FROM `tabLoyalty Point Entry`
            WHERE customer = %s AND loyalty_program = %s
            AND expiry_date >= %s
        """, (customer.name, loyalty_program.name, today()), as_dict=1)
        
        current_points = points[0].points if points and points[0].points else 0

        for tier in loyalty_program.collection_rules:
            if current_points >= tier.min_spent:
                return tier.name

        return "Classic"

    def get_rule(self, event_type):
        """Get rule for event type"""
        for rule in self.rules:
            if rule.event_type.lower().replace(" ", "_") == event_type.lower().replace(" ", "_"):
                return rule
        return None

    def log_notification(self, customer, event_type, status, message, coupon=None, loyalty_tier=None):
        """Log notification details"""
        frappe.get_doc({
            "doctype": "Notification Log",
            "customer": customer.name,
            "event_type": event_type,
            "status": status,
            "message": message,
            "loyalty_program": customer.loyalty_program,
            "loyalty_tier": loyalty_tier,
            "coupon": coupon
        }).insert(ignore_permissions=True)

def process_daily_notifications():
    """Process all daily notifications"""
    manager = NotificationManager()
    today_date = today()

    # Process birthdays
    birthday_customers = frappe.get_all(
        "Customer",
        filters={
            "custom_birthday": ["like", f"%-{today_date[5:]}"],
            "mobile_no": ["!=", ""]
        },
        fields=["name", "customer_name", "mobile_no", "loyalty_program", "loyalty_program_tier"]
    )
    
    for cust in birthday_customers:
        customer = frappe.get_doc("Customer", cust.name)
        manager.send_tier_notification(customer, "Birthday")

    # Process membership anniversaries
    member_customers = frappe.get_all(
        "Customer",
        filters={
            "custom_member_date": ["like", f"%-{today_date[5:]}"],
            "mobile_no": ["!=", ""],
            "loyalty_program": ["!=", ""]
        },
        fields=["name", "customer_name", "mobile_no", "loyalty_program"]
    )
    
    for cust in member_customers:
        customer = frappe.get_doc("Customer", cust.name)
        manager.send_notification(customer, "Membership Anniversary")

def on_customer_create(doc, method):
    """Handle new customer registration"""
    manager = NotificationManager()
    manager.send_notification(doc, "New Registration")
