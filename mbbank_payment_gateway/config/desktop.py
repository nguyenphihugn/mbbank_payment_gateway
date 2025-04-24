# Copyright (c) 2025, Your Company and contributors
# For license information, please see license.txt

import frappe
import requests
import json
import uuid
from frappe import _
from frappe.model.document import Document

class MBBankSettings(Document):
    def validate(self):
        # Validate required fields
        if not self.client_id or not self.client_secret or not self.base_url:
            frappe.throw(_("Client ID, Client Secret, and Base URL are required"))

@frappe.whitelist()
def get_mbbank_settings():
    """Get MB Bank API settings."""
    return frappe.get_doc("MB Bank Settings")

class MBBankPaymentGateway:
    def __init__(self):
        self.settings = frappe.get_doc("MB Bank Settings")
        self.client_id = self.settings.client_id
        self.client_secret = self.settings.client_secret
        self.base_url = self.settings.base_url
        self.access_token = None

    def generate_client_message_id(self):
        """Generate a unique client message ID."""
        return str(uuid.uuid4())

    def generate_transaction_id(self):
        """Generate a unique transaction ID."""
        return str(uuid.uuid4())

    def get_access_token(self):
        """Get access token for MB Bank API."""
        if self.access_token:
            return self.access_token

        url = f"{self.settings.auth_url}/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        try:
            response = requests.post(url, headers=headers, data=data)
            response.raise_for_status()
            result = response.json()
            self.access_token = result.get("access_token")
            return self.access_token
        except requests.exceptions.RequestException as e:
            frappe.log_error(f"Failed to get access token: {str(e)}", "MB Bank Payment Gateway")
            frappe.throw(_("Failed to authenticate with MB Bank API"))

    def create_payment_request(self, amount, description, redirect_url, user_info=None):
        """Create payment request to MB Bank."""
        token = self.get_access_token()
        
        client_message_id = self.generate_client_message_id()
        transaction_id = self.generate_transaction_id()
        
        url = f"{self.base_url}/v1.0/payment/request"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        payload = {
            "clientMessageId": client_message_id,
            "transactionId": transaction_id,
            "amount": amount,
            "description": description,
            "redirectUrl": redirect_url
        }
        
        if user_info:
            payload["userInfo"] = user_info
            
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            
            # Save payment request to database
            payment_request = frappe.get_doc({
                "doctype": "MB Bank Payment Request",
                "client_message_id": client_message_id,
                "transaction_id": transaction_id,
                "amount": amount,
                "description": description,
                "status": "Initiated",
                "payment_url": result.get("paymentUrl"),
                "request_id": result.get("requestId")
            })
            payment_request.insert(ignore_permissions=True)
            
            return {
                "status": "success",
                "payment_url": result.get("paymentUrl"),
                "request_id": result.get("requestId"),
                "transaction_id": transaction_id
            }
            
        except requests.exceptions.RequestException as e:
            frappe.log_error(f"Failed to create payment request: {str(e)}", "MB Bank Payment Gateway")
            frappe.throw(_("Failed to create payment request"))

    def verify_payment(self, transaction_id):
        """Verify payment status with MB Bank."""
        token = self.get_access_token()
        client_message_id = self.generate_client_message_id()
        
        url = f"{self.base_url}/v1.0/payment/status"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        payload = {
            "clientMessageId": client_message_id,
            "transactionId": transaction_id
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            
            # Update payment request status
            payment_request = frappe.get_doc("MB Bank Payment Request", {"transaction_id": transaction_id})
            payment_request.status = result.get("status", "Unknown")
            payment_request.response_data = json.dumps(result)
            payment_request.save(ignore_permissions=True)
            
            return {
                "status": "success",
                "payment_status": result.get("status"),
                "transaction_id": transaction_id
            }
            
        except requests.exceptions.RequestException as e:
            frappe.log_error(f"Failed to verify payment: {str(e)}", "MB Bank Payment Gateway")
            frappe.throw(_("Failed to verify payment status"))

@frappe.whitelist(allow_guest=True)
def payment_callback():
    """Handle payment callback from MB Bank."""
    try:
        data = json.loads(frappe.request.data)
        transaction_id = data.get("transactionId")
        status = data.get("status")
        
        if not transaction_id:
            frappe.throw(_("Invalid callback data"))
            
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

@frappe.whitelist()
def create_course_payment(course, user=None):
    """Create payment for course enrollment."""
    if not user:
        user = frappe.session.user
        
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
    callback_url = frappe.utils.get_url("/api/method/mbbank_payment_gateway.api.payment_callback")
    redirect_url = frappe.utils.get_url(f"/courses/{course}")
    
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
    payment_request.save(ignore_permissions=True)
    
    return {
        "status": "success",
        "payment_url": result.get("payment_url")
    }