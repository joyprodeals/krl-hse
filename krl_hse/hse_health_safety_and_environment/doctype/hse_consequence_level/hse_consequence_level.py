from frappe.model.document import Document

from krl_hse.utils.risk import check_scale_level


class HSEConsequenceLevel(Document):
	def validate(self):
		check_scale_level(self)
