from datetime import datetime, timedelta
from decimal import Decimal
import logging
import mysql.connector
from mysql.connector import Error
from typing import Optional, Dict, List
from dataclasses import dataclass

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class CustomerTierData:
    customer: str
    loyalty_program: str
    current_tier: str
    previous_total: Decimal
    current_total: Decimal

class DatabaseConnection:
    def __init__(self):
        self.connection = None
        self.config = {
            'host': 'database-3.cj20go4siene.ap-southeast-1.rds.amazonaws.com',
            'user': 'admin',
            'password': 'W+b(+uMl*SL!N_P}FV26<Mzb?30F',
            'database': 'erpnext_prod'
        }

    def connect(self):
        try:
            if not self.connection or not self.connection.is_connected():
                self.connection = mysql.connector.connect(**self.config)
                logger.info("Database connection established successfully")
        except Error as e:
            logger.error(f"Error connecting to database: {e}")
            raise

    def disconnect(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.info("Database connection closed")

    def execute_query(self, query: str, params: tuple = None) -> List[Dict]:
        try:
            self.connect()
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(query, params)
            result = cursor.fetchall()
            cursor.close()
            return result
        except Error as e:
            logger.error(f"Error executing query: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {params}")
            raise
        finally:
            self.disconnect()

    def execute_update(self, query: str, params: tuple = None) -> None:
        try:
            self.connect()
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            cursor.close()
        except Error as e:
            logger.error(f"Error executing update: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {params}")
            self.connection.rollback()
            raise
        finally:
            self.disconnect()

class LoyaltyTierProcessor:
    def __init__(self):
        self.db = DatabaseConnection()
        
    def get_tier_changes(self, yesterday: str, day_before_yesterday: str) -> List[CustomerTierData]:
        """
        Get customers with potential tier changes using a single optimized query
        """
        query = """
        WITH CurrentTotals AS (
            -- Calculate totals including yesterday's purchases
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
            -- Calculate totals up to day before yesterday
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
        """
        
        try:
            results = self.db.execute_query(
                query, 
                (yesterday, yesterday, 
                 day_before_yesterday, day_before_yesterday,
                 yesterday)
            )
            
            return [
                CustomerTierData(
                    customer=row['customer'],
                    loyalty_program=row['loyalty_program'],
                    current_tier=row['current_tier'],
                    previous_total=Decimal(str(row['previous_total'])),
                    current_total=Decimal(str(row['current_total']))
                )
                for row in results
            ]
        except Exception as e:
            logger.error(f"Error getting tier changes: {e}")
            raise

    def get_loyalty_program_tiers(self, loyalty_program: str) -> List[Dict]:
        """Get tier rules for a loyalty program"""
        query = """
        SELECT tier_name, min_spent
        FROM `tabLoyalty Program Collection`
        WHERE parent = %s
        ORDER BY min_spent DESC
        """
        return self.db.execute_query(query, (loyalty_program,))

    def determine_tier(self, total_spent: Decimal, tiers: List[Dict]) -> str:
        """Determine tier based on total spent"""
        for tier in tiers:
            if total_spent >= Decimal(str(tier['min_spent'])):
                return tier['tier_name']
        return "Classic"

    # def update_customer_tier(self, customer: str, new_tier: str) -> None:
    #     """Update customer's loyalty tier"""
    #     query = """
    #     UPDATE `tabCustomer`
    #     SET loyalty_program_tier = %s
    #     WHERE name = %s
    #     """
    #     self.db.execute_update(query, (new_tier, customer))

    def send_tier_change_notification(self, customer: str, new_tier: str) -> None:
        """Send notification for tier change"""
        query = """
        INSERT INTO `tabNotification Log`
        (customer, event_type, status, message, loyalty_tier)
        VALUES (%s, %s, %s, %s, %s)
        """
        message = f"Congratulations! You have been upgraded to {new_tier} tier."
        # self.db.execute_update(
        #     query,
        #     (customer, "Tier_Change", "Success", message, new_tier)
        # )

    def process_loyalty_tier_changes(self):
        """Main function to process tier changes"""
        try:
            # yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            # day_before_yesterday = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
            yesterday = (datetime.now()).strftime('%Y-%m-%d')
            day_before_yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            logger.info("Starting loyalty tier change processing")
            
            # Get all potential tier changes
            customers_data = self.get_tier_changes(yesterday, day_before_yesterday)
            
            for customer_data in customers_data:
                try:
                    # Get loyalty program tiers
                    tiers = self.get_loyalty_program_tiers(customer_data.loyalty_program)
                    
                    # Determine previous and new tiers
                    previous_tier = self.determine_tier(customer_data.previous_total, tiers)
                    new_tier = self.determine_tier(customer_data.current_total, tiers)
                    
                    # If tier has changed, update and notify
                    if new_tier != previous_tier:
                        logger.info(
                            f"Tier change for {customer_data.customer}: "
                            f"{previous_tier} -> {new_tier}"
                        )
                        logger.info(
                            f"Previous total: {customer_data.previous_total}, "
                            f"Current total: {customer_data.current_total}"
                        )
                        
                        # self.update_customer_tier(customer_data.customer, new_tier)
                        self.send_tier_change_notification(customer_data.customer, new_tier)
                        
                except Exception as e:
                    logger.error(
                        f"Error processing customer {customer_data.customer}: {e}"
                    )
                    continue
                    
            logger.info("Completed loyalty tier change processing")
            
        except Exception as e:
            logger.error(f"Error in process_loyalty_tier_changes: {e}")
            raise

def main():
    processor = LoyaltyTierProcessor()
    try:
        processor.process_loyalty_tier_changes()
    except Exception as e:
        logger.error(f"Failed to process loyalty tier changes: {e}")

if __name__ == "__main__":
    main()