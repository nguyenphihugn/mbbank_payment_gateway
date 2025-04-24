import frappe
from frappe.utils import now_datetime, add_days
from mbbank_payment_gateway.mbbank_payment_gateway.doctype.mb_bank_settings.mb_bank_settings import MBBankPaymentGateway

def verify_pending_payments():
    """Verify pending payments with MB Bank."""
    # Get pending payments created in the last 24 hours
    pending_payments = frappe.get_all(
        "MB Bank Payment Request",
        filters={
            "status": ["in", ["Initiated", "Pending"]],
            "creation": [">", add_days(now_datetime(), -1)]
        },
        fields=["name", "transaction_id", "reference_doctype", "reference_name"]
    )
    
    if not pending_payments:
        return
    
    mbbank = MBBankPaymentGateway()
    
    for payment in pending_payments:
        try:
            result = mbbank.verify_payment(payment.transaction_id)
            
            # Update enrollment if payment successful
            if result.get("payment_status") == "SUCCESS" and payment.reference_doctype == "LMS Course Enrollment":
                enrollment = frappe.get_doc("LMS Course Enrollment", payment.reference_name)
                enrollment.paid = 1
                enrollment.save(ignore_permissions=True)
                
                # Log success message
                frappe.logger().info(f"Successfully processed payment: {payment.transaction_id} for enrollment {payment.reference_name}")
                
        except Exception as e:
            frappe.logger().error(f"Error verifying payment {payment.transaction_id}: {str(e)}")
            continue