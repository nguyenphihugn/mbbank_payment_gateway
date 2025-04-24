frappe.provide("frappe.mbbank_payment");

frappe.mbbank_payment = {
	initPayment: function (courseId) {
		frappe.call({
			method: "mbbank_payment_gateway.api.create_course_payment",
			args: {
				course: courseId,
			},
			callback: function (r) {
				if (r.message && r.message.status === "success") {
					window.location.href = r.message.payment_url;
				} else {
					frappe.msgprint(__("Payment initiation failed. Please try again."));
				}
			},
		});
	},

	checkPaymentStatus: function (transactionId, callback) {
		frappe.call({
			method: "mbbank_payment_gateway.api.check_payment_status",
			args: {
				transaction_id: transactionId,
			},
			callback: function (r) {
				if (callback) callback(r.message);
			},
		});
	},

	showPaymentButton: function (courseId, isCourseEnrollmentPage) {
		if (!courseId) return;

		frappe.call({
			method: "mbbank_payment_gateway.api.get_course_payment_status",
			args: {
				course: courseId,
			},
			callback: function (r) {
				if (r.message && r.message.should_show_payment) {
					const paymentBtn = `
                        <div class="mt-4">
                            <button class="btn btn-primary btn-sm mb-payment-btn" 
                                data-course="${courseId}">
                                ${__("Pay Now with MB Bank")}
                            </button>
                        </div>
                    `;

					if (isCourseEnrollmentPage) {
						$(".course-enrollment-actions").append(paymentBtn);
					} else {
						$(".course-details").append(paymentBtn);
					}

					$(".mb-payment-btn").on("click", function () {
						const courseId = $(this).data("course");
						frappe.mbbank_payment.initPayment(courseId);
					});
				}
			},
		});
	},
};

// Initialize payment buttons on course pages
$(document).ready(function () {
	if (window.location.pathname.includes("/courses/")) {
		const courseId = window.location.pathname.split("/").pop();
		const isCourseEnrollmentPage = window.location.pathname.includes("/learn");

		if (courseId) {
			frappe.mbbank_payment.showPaymentButton(courseId, isCourseEnrollmentPage);
		}
	}

	// Handle payment return from MB Bank
	const urlParams = new URLSearchParams(window.location.search);
	const transactionId = urlParams.get("transaction_id");
	const status = urlParams.get("status");

	if (transactionId && status) {
		frappe.mbbank_payment.checkPaymentStatus(transactionId, function (result) {
			if (result && result.payment_status === "SUCCESS") {
				frappe.show_alert(
					{
						message: __("Payment successful! You have been enrolled in the course."),
						indicator: "green",
					},
					5
				);

				// Reload page after 2 seconds to show updated enrollment status
				setTimeout(function () {
					window.location.reload();
				}, 2000);
			} else if (result && result.payment_status === "FAILED") {
				frappe.show_alert(
					{
						message: __("Payment failed. Please try again."),
						indicator: "red",
					},
					5
				);
			}
		});
	}
});
