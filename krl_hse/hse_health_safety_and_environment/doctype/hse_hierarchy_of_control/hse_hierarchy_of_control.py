import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class HSEHierarchyofControl(Document):
	def validate(self):
		if cint(self.control_order) < 1:
			frappe.throw(_("Order must be 1 or more."))
