import frappe


def execute():
	"""Sites set up before the review reminders have no Scheduled Review revision trigger. Add it once."""
	if not frappe.db.exists("DocType", "HSE Revision Trigger"):
		return
	if frappe.db.exists("HSE Revision Trigger", "Scheduled Review"):
		return
	frappe.get_doc(
		{
			"doctype": "HSE Revision Trigger",
			"trigger_name": "Scheduled Review",
			"description": "The review date came round. The document is checked and approved again, with or without a change",
		}
	).insert(ignore_permissions=True)
