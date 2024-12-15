import frappe
from frappe import _
from frappe.utils import today, add_days
from frappe.core.doctype.sms_settings.sms_settings import send_sms
import random
import string

class NotificationManager:
    def __init__(self):
        self.sms_settings = frappe.get_doc("SMS Settings")
        self.load_rules()
        
    
    def load_rules(self):
        """Load all active notification rules"""
        self.rules = frappe.get_all(
            "Notification Rule",
            filters={"enabled": 1},
            fields=["*"]
        )
        
        # Load child table data for each rule
        for rule in self.rules:
            rule.tier_discounts = frappe.get_all(
                "Tier Discount",
                filters={"parent": rule.name},
                fields=["loyalty_program", "tier_name", "discount_value"],
                order_by="idx"
            )


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
            )

            # Log success
            self.log_notification(
                customer, event_type, "Success",
                message,
                None
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
            pricing_rule_title = event_type + "_" + customer_tier
            
            # Check if PricingRule exists update discount_value as notification rule
            pricing_rule_name = frappe.db.exists("Pricing Rule", {"title": pricing_rule_title})
            
            fields = {
                "title": pricing_rule_title,
                "apply_on": "Transaction",
                "price_or_product_discount": "Price",
                "coupon_code_based": 1,
                "selling": 1,
                "buying": 0,
                "valid_from": "2024-12-15",
                "company": "LAC",
                "currency": "MNT",
                "rate_or_discount": "Discount Amount",
                "apply_discount_on": "Grand Total",
                "discount_amount": discount_value or 0.0,  # taken from notification rule
                "disable": 0
            }
            
            pr_doc = None
            if pricing_rule_name:
                # Update existing pricing rule
                pr_doc = frappe.get_doc("Pricing Rule", pricing_rule_name)
                for key, val in fields.items():
                    pr_doc.set(key, val)
                pr_doc.save()
            # If not exists then create PricingRule
            else:
                pr_doc = frappe.get_doc({
                    "doctype": "Pricing Rule",
                    **fields
                })
                pr_doc.insert(ignore_permissions=True)
            
            # Create Coupon
            coupon_doc = self.create_coupon(customer, rule, pr_doc.name)
            
            # Prepare message by replacing placeholders
            message = rule.message_template.replace(
                "discount_value", str(discount_value)
            ).replace(
                "customer_name", customer.customer_name
            ).replace(
                "validity_days", str(rule.validity_days)
            ).replace(
                "loyalty_tier", customer_tier or "Classic"
            ).replace(
                "coupon_code", coupon_doc.coupon_code
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

    def create_coupon(self, customer, notif_rule, pricing_rule_name):
        """Create coupon based on notification rule"""
        coupon_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        coupon = frappe.get_doc({
            "doctype": "Coupon Code",
            "coupon_name": coupon_code,
            "coupon_code": coupon_code,
            "coupon_type": "Gift Card",
            "pricing_rule": pricing_rule_name,
            "customer": customer.name,
            "valid_from": today(),
            "valid_upto": add_days(today(), notif_rule.validity_days)
        })
        coupon.insert(ignore_permissions=True)
        return coupon

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
    
    
    # Process birthday notifs
    today_date = today()
    month_day = today_date[5:]  # Get MM-DD

    birthday_customers = frappe.db.sql("""
        SELECT name, customer_name, mobile_no, loyalty_program, loyalty_program_tier 
        FROM `tabCustomer` 
        WHERE DATE_FORMAT(custom_birthday, '%%m-%%d') = %s 
        AND mobile_no != ''
    """, month_day, as_dict=1)
    
    for cust in birthday_customers:
        customer = frappe.get_doc("Customer", cust.name)
        manager.send_tier_notification(customer, "Birthday")

    
    # Process membership anniversaries
    member_customers = frappe.db.sql("""
        SELECT name, customer_name, mobile_no, loyalty_program, loyalty_program_tier 
        FROM `tabCustomer` 
        WHERE DATE_FORMAT(custom_member_date, '%%m-%%d') = %s 
        AND mobile_no != ''
    """, month_day, as_dict=1)
    
    for cust in member_customers:
        customer = frappe.get_doc("Customer", cust.name)
        manager.send_notification(customer, "Membership Anniversary")
        
    
    # """Process loyalty tier changes based on yesterday's purchases"""
    yesterday = add_days(today(), -1)
    day_before_yesterday = add_days(today(), -2)

    # Get customers who made purchases yesterday
    tier_changes = frappe.db.sql("""
        WITH CurrentTotals AS (
            SELECT 
                customer,
                loyalty_program,
                SUM(purchase_amount) as current_total
            FROM `tabLoyalty Point Entry`
            WHERE posting_date <= %s
                AND expiry_date >= %s
                AND loyalty_points > 0
            GROUP BY customer, loyalty_program
        ),
        PreviousTotals AS (
            SELECT 
                customer,
                loyalty_program,
                SUM(purchase_amount) as previous_total
            FROM `tabLoyalty Point Entry`
            WHERE posting_date <= %s
                AND expiry_date >= %s
                AND loyalty_points > 0
            GROUP BY customer, loyalty_program
        )
        SELECT 
            c.customer,
            c.loyalty_program,
            COALESCE(p.previous_total, 0) as previous_total,
            COALESCE(c.current_total, 0) as current_total,
            cust.loyalty_program_tier as current_tier
        FROM CurrentTotals c
        LEFT JOIN PreviousTotals p 
            ON c.customer = p.customer 
            AND c.loyalty_program = p.loyalty_program
        INNER JOIN `tabCustomer` cust 
            ON c.customer = cust.name
        WHERE EXISTS (
            SELECT 1 
            FROM `tabLoyalty Point Entry` lpe
            WHERE lpe.customer = c.customer
                AND lpe.posting_date = %s
        )
    """, (yesterday, yesterday, day_before_yesterday, day_before_yesterday, yesterday), as_dict=1)
    
    loyalty_program = frappe.get_doc("Loyalty Program", "LAC CLUB")
    tier_changed = False

    for change in tier_changes:
        customer = frappe.get_doc("Customer", change.customer)
        
        # Get tier levels sorted by min_spent
        tier_levels = sorted(
            [d.as_dict() for d in loyalty_program.collection_rules],
            key=lambda rule: rule.min_spent,
            reverse=True
        )

        # Determine previous and new tiers
        def get_tier(total_spent):
            for tier in tier_levels:
                if total_spent <= tier.min_spent:
                    return tier.tier_name
            return "Classic"

        previous_tier = get_tier(change.previous_total)
        new_tier = get_tier(change.current_total)

        # If tier has changed, send notification
        if new_tier != previous_tier:
            tier_changed = True
            customer.loyalty_program_tier = new_tier
            manager.send_tier_notification(customer, "Loyalty Upgrade")
            
            # Log the change
            manager.log_notification(customer, "Tier_Change", "Success", f"Tier changed from {previous_tier} to {new_tier}", new_tier)
    
    if not tier_changed:
        frappe.get_doc({
            "doctype": "Notification Log",
            "customer": "",
            "event_type": "Loyalty Upgrade",
            "status": "Success",
            "message": f"No tier changed on {yesterday}"
        }).insert(ignore_permissions=True)
    

def on_customer_create(doc, method):
    """Handle new customer registration"""
    manager = NotificationManager()
    manager.send_notification(doc, "New Registration")
