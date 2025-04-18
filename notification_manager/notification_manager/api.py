import frappe


@frappe.whitelist()
def get_item_with_qty():
    """
    Fetch items with their actual quantities using a SQL query.
    """
    try:
        # Execute the SQL query
        query = """
            SELECT 
                ti.*, 
                tb.actual_qty 
            FROM 
                `tabItem` ti
            LEFT JOIN 
                `tabBin` tb 
            ON 
                ti.name = tb.item_code
        """
        result = frappe.db.sql(query, as_dict=True)  # Fetch results as a list of dictionaries
        return result
    except Exception as e:
        # Log error and return error message
        frappe.log_error(frappe.get_traceback(), 'API Error: get_item_with_qty')
        return {'error': str(e)}
