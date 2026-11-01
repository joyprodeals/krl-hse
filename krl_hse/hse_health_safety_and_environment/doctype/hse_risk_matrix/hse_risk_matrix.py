import frappe
from frappe import _
from frappe.model.document import Document

from krl_hse.utils.risk import matrix_preview_html


class HSERiskMatrix(Document):
	def validate(self):
		seen = set()
		for row in self.cells:
			pair = (row.consequence, row.likelihood)
			if pair in seen:
				frappe.throw(_("Row {0}: {1} with {2} is already in the matrix.").format(row.idx, *pair))
			seen.add(pair)

		missing = [
			f"{c} / {l}"
			for c in frappe.get_all("HSE Consequence Level", pluck="name", order_by="level")
			for l in frappe.get_all("HSE Likelihood Level", pluck="name", order_by="level")
			if (c, l) not in seen
		]
		if missing:
			frappe.msgprint(
				_(
					"These combinations have no severity yet, so a HIRA line using them cannot be rated: {0}"
				).format(", ".join(missing[:10]) + (" ..." if len(missing) > 10 else "")),
				indicator="orange",
			)

	def onload(self):
		self.set_onload("matrix_preview", matrix_preview_html())
