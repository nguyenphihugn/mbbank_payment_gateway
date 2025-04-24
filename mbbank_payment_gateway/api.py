import frappe
import json
import requests
from frappe import _
from frappe.utils import now_datetime, get_url
from mbbank_payment_gateway.mbbank_payment_gateway.doctype.mb_bank_settings.mb_bank_settings import MBBankPaymentGateway

@frappe.whitelist()
def get_course_payment_status(course):
    """Check if payment button should be shown for a course."""
    if not frappe.db.exists("LMS Course", course):
        return {"should_show_payment": False}
    
    course_doc = frappe.get_doc("LMS Course", course)
    if not course_doc.is_paid:
        return {"should_show_payment": False}
    
    user = frappe.session.user
    if user == "Guest":
        return {"should_show_payment": True}
        
    # Check if user is already enrolled and paid
    enrollment = frappe.get_all(
        "LMS Course Enrollment",
        filters={"course": course, "user": user, "paid": 1},
        limit=1
    )
    
    if enrollment:
        return {"should_show_payment": False}
    
    # Check if user has a pending payment
    pending_payment = frappe.get_all(
        "MB Bank Payment Request",
        filters={
            "reference_doctype": "LMS Course Enrollment",
            "reference_name": ["in", frappe.get_all("LMS Course Enrollment", 
                               filters={"course": course, "user": user},
                               pluck="name")],
            "status": ["in", ["Initiated", "Pending"]]
        },
        limit=1
    )
    
    if pending_payment:
        return {"should_show_payment": False}
        
    # User needs to pay
    return {"should_show_payment": True}

@frappe.whitelist()
def create_course_payment(course, user=None):
    """Create payment for course enrollment."""
    if not user:
        user = frappe.session.user
        if user == "Guest":
            frappe.throw(_("Please login to enroll in a paid course"))
        
    course_doc = frappe.get_doc("LMS Course", course)
    
    if not course_doc.is_paid:
        frappe.throw(_("This course does not require payment"))
        
    # Check if user is already enrolled and paid
    enrollment = frappe.get_all(
        "LMS Course Enrollment",
        filters={"course": course, "user": user, "paid": 1},
        limit=1
    )
    
    if enrollment:
        frappe.throw(_("You are already enrolled in this course"))
        
    # Create or get enrollment
    existing_enrollment = frappe.get_all(
        "LMS Course Enrollment",
        filters={"course": course, "user": user},
        limit=1
    )
    
    if existing_enrollment:
        enrollment_name = existing_enrollment[0].name
        enrollment = frappe.get_doc("LMS Course Enrollment", enrollment_name)
    else:
        enrollment = frappe.get_doc({
            "doctype": "LMS Course Enrollment",
            "course": course,
            "user": user
        })
        enrollment.insert(ignore_permissions=True)
        
    # Create payment request
    mbbank = MBBankPaymentGateway()
    callback_url = get_url("/api/method/mbbank_payment_gateway.api.payment_callback")
    redirect_url = get_url(f"/courses/{course}")
    
    user_info = {
        "name": frappe.db.get_value("User", user, "full_name"),
        "email": user
    }
    
    result = mbbank.create_payment_request(
        amount=course_doc.amount,
        description=f"Payment for course: {course_doc.title}",
        redirect_url=redirect_url,
        user_info=user_info
    )
    
    # Update payment request with reference
    payment_request = frappe.get_doc("MB Bank Payment Request", {"transaction_id": result.get("transaction_id")})
    payment_request.reference_doctype = "LMS Course Enrollment"
    payment_request.reference_name = enrollment.name
    payment_request.user = user
    payment_request.save(ignore_permissions=True)
    
    return {
        "status": "success",
        "payment_url": result.get("payment_url")
    }

@frappe.whitelist()
def check_payment_status(transaction_id):
    """Check payment status for a transaction."""
    if not transaction_id:
        frappe.throw(_("Invalid transaction ID"))
        
    payment_request = frappe.get_doc("MB Bank Payment Request", {"transaction_id": transaction_id})
    
    # If status is still pending, verify with MB Bank
    if payment_request.status in ["Initiated", "Pending"]:
        mbbank = MBBankPaymentGateway()
        result = mbbank.verify_payment(transaction_id)
        
        # Update enrollment if payment successful
        if result.get("payment_status") == "SUCCESS" and payment_request.reference_doctype == "LMS Course Enrollment":
            enrollment = frappe.get_doc("LMS Course Enrollment", payment_request.reference_name)
            enrollment.paid = 1
            enrollment.save(ignore_permissions=True)
            
        return result
    else:
        # Return existing status
        return {
            "payment_status": payment_request.status,
            "transaction_id": transaction_id
        }

@frappe.whitelist(allow_guest=True)
def payment_callback():
    """Handle payment callback from MB Bank."""
    try:
        data = json.loads(frappe.request.data)
        transaction_id = data.get("transactionId")
        status = data.get("status")
        
        if not transaction_id:
            frappe.log_error("Invalid callback data: " + str(data), "MB Bank Payment Gateway")
            return {"status": "error", "message": "Invalid callback data"}
            
        # Update payment request status
        payment_request = frappe.get_doc("MB Bank Payment Request", {"transaction_id": transaction_id})
        payment_request.status = status
        payment_request.callback_data = json.dumps(data)
        payment_request.save(ignore_permissions=True)
        
        # If payment is successful, update course enrollment
        if status == "SUCCESS" and payment_request.reference_doctype == "LMS Course Enrollment":
            enrollment = frappe.get_doc("LMS Course Enrollment", payment_request.reference_name)
            enrollment.paid = 1
            enrollment.save(ignore_permissions=True)
            
        return {"status": "success"}
    except Exception as e:
        frappe.log_error(f"Payment callback error: {str(e)}", "MB Bank Payment Gateway")
        return {"status": "error", "message": str(e)}

def validate_course_enrollment(doc, method):
    """Validate course enrollment when created/updated."""
    # Only process if this is a course enrollment for a paid course
    if doc.doctype != "LMS Course Enrollment":
        return
        
    course_doc = frappe.get_doc("LMS Course", doc.course)
    if not course_doc.is_paid:
        return
        
    # If paid flag is being set, check if there's a successful payment
    if doc.paid == 1 and not doc.get_doc_before_save():
        # New enrollment being set as paid
        successful_payment = frappe.get_all(
            "MB Bank Payment Request",
            filters={
                "reference_doctype": "LMS Course Enrollment",
                "reference_name": doc.name,
                "status": "SUCCESS"
            },
            limit=1
        )
        
        if not successful_payment and not frappe.flags.in_test and not frappe.flags.in_install:
            frappe.throw(_("Cannot mark enrollment as paid without successful payment"))