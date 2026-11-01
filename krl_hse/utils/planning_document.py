"""Shared parts of the planning documents that belong to a Method Statement: HIRA and SOP.

Both name the Method Statement they are made for, take branch, work and project details from it, and
follow the parent-document rule of HSE Settings (Approved only, Any state, Not required). Both number
the rows they are referred to by (HIRA lines, SOP steps) so a reference stays with its row.
"""

import re

import frappe
from frappe import _

from krl_hse.utils.controlled_document import ControlledDocument, get_approved_state, get_settings


def assign_row_refs(rows, fieldname, prefix, label):
	"""Give each row without one a reference (L1, S2, ...) that stays with it when rows move or go.

	Raises if a reference is used twice. Returns nothing: the rows are changed in place.
	"""
	used = [row.get(fieldname) for row in rows if row.get(fieldname)]
	repeated = sorted({ref for ref in used if used.count(ref) > 1})
	if repeated:
		frappe.throw(_("{0} {1} is used more than once.").format(label, ", ".join(repeated)))

	pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
	numbers = [int(m.group(1)) for ref in used if (m := pattern.match(ref))]
	following = max(numbers, default=0) + 1
	for row in rows:
		if not row.get(fieldname):
			row.set(fieldname, f"{prefix}{following}")
			following += 1


class MethodStatementDocument(ControlledDocument):
	"""A controlled document made for one Method Statement."""

	def before_insert(self):
		# Numbering needs the branch, and numbering comes before validation.
		self.fill_from_method_statement()

	def before_validate(self):
		self.fill_from_method_statement()

	def fill_from_method_statement(self):
		"""Take branch, work and the project details from the Method Statement."""
		if not self.method_statement:
			return

		ms = frappe.db.get_value(
			"HSE Method Statement",
			self.method_statement,
			[
				"branch",
				"work_order",
				"name_of_work",
				"client_name",
				"client_format_applies",
				"client_format_reference",
			],
			as_dict=True,
		)
		if not ms:
			return

		if not self.branch:
			self.branch = ms.branch
		elif ms.branch != self.branch:
			frappe.throw(
				_("Method Statement {0} belongs to branch {1}, but this {2} is for branch {3}.").format(
					frappe.bold(self.method_statement),
					frappe.bold(ms.branch),
					self.doctype,
					frappe.bold(self.branch),
				)
			)

		if not self.work_order:
			self.work_order = ms.work_order
		elif ms.work_order and ms.work_order != self.work_order:
			frappe.throw(
				_("Method Statement {0} is for work {1}, not for work {2}.").format(
					frappe.bold(self.method_statement),
					frappe.bold(ms.work_order),
					frappe.bold(self.work_order),
				)
			)

		if self.meta.has_field("name_of_work") and not self.name_of_work:
			self.name_of_work = ms.name_of_work
		if self.meta.has_field("client_name") and not self.client_name:
			self.client_name = ms.client_name

		if self.is_new() and not self.previous_revision and ms.client_format_applies:
			self.client_format_applies = 1
			self.client_format_reference = self.client_format_reference or ms.client_format_reference

	def check_method_statement(self):
		"""Apply the parent-document rule of HSE Settings when the Method Statement is chosen."""
		rule = get_settings().parent_document_rule or "Approved only"

		if not self.method_statement:
			if rule != "Not required":
				frappe.throw(
					_("Choose the Method Statement this {0} is for. It cannot be made on its own.").format(
						self.doctype
					),
					title=_("Method Statement needed"),
				)
			return

		# A revision keeps the Method Statement it was first approved against.
		if self.previous_revision and self.is_new():
			return
		if not (self.is_new() or self.has_value_changed("method_statement")):
			return

		state = frappe.db.get_value("HSE Method Statement", self.method_statement, "workflow_state")
		if rule == "Approved only" and state != get_approved_state():
			frappe.throw(
				_("Method Statement {0} is {1}. A {2} can only be made for an {3} Method Statement.").format(
					frappe.bold(self.method_statement),
					(state or _("not yet in any state")).lower(),
					self.doctype,
					get_approved_state().lower(),
				),
				title=_("Method Statement not approved"),
			)

	def check_area(self):
		if not self.area:
			return

		branch, work_order, disabled = frappe.db.get_value(
			"HSE Workplace Area", self.area, ["branch", "work_order", "disabled"]
		)
		if branch != self.branch:
			frappe.throw(
				_("Area {0} belongs to branch {1}, but this {2} is for branch {3}.").format(
					frappe.bold(self.area), frappe.bold(branch), self.doctype, frappe.bold(self.branch)
				)
			)
		if work_order and self.work_order and work_order != self.work_order:
			frappe.throw(
				_("Area {0} belongs to work {1}, not to work {2}.").format(
					frappe.bold(self.area), frappe.bold(work_order), frappe.bold(self.work_order)
				)
			)
		if disabled and (self.is_new() or self.has_value_changed("area")):
			frappe.throw(_("Area {0} is disabled.").format(frappe.bold(self.area)))


@frappe.whitelist()
def method_statement_details(method_statement):
	"""What a form copies from the chosen Method Statement."""
	frappe.has_permission("HSE Method Statement", "read", doc=method_statement, throw=True)
	ms = frappe.get_doc("HSE Method Statement", method_statement)
	return {
		"branch": ms.branch,
		"work_order": ms.work_order,
		"name_of_work": ms.name_of_work,
		"client_name": ms.client_name,
		"areas": [row.area for row in ms.areas if row.area],
		"works": [row.work_name for row in ms.works if row.work_name],
		"client_format_applies": ms.client_format_applies,
		"client_format_reference": ms.client_format_reference,
	}
