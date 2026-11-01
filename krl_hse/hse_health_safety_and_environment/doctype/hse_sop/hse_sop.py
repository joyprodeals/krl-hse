import frappe
from frappe import _
from frappe.utils import add_months, getdate, nowdate

from krl_hse.utils.controlled_document import get_approved_state, get_review_months
from krl_hse.utils.planning_document import MethodStatementDocument, assign_row_refs


class HSESOP(MethodStatementDocument):
	"""Standard Operating Procedure, KRL/HSE/SOP/1 (BRD 6.1.3).

	It belongs to a Method Statement and covers some or all of its works. It has a validity date and
	is reviewed before it runs out. A new SOP goes through four approval levels, a revision through
	three (the Branch HSE Head step is skipped, because the Branch HSE Head prepares the revision).
	When it is approved, the people on the distribution list are notified.
	"""

	not_carried_to_revision = (
		*MethodStatementDocument.not_carried_to_revision,
		"validity_date",
		"client_approval_reference",
		"client_approval_date",
	)

	def before_insert(self):
		super().before_insert()
		self.fill_basic_ppe()
		self.prefill_validity()

	def fill_basic_ppe(self):
		"""A new SOP starts with the basic PPE, as a new Method Statement does."""
		if self.ppe or self.previous_revision:
			return
		for row in basic_ppe():
			self.append("ppe", row)

	def prefill_validity(self):
		"""When HSE Settings gives a review period for SOPs, suggest the validity date from it."""
		months = get_review_months(self.doctype)
		if months and not self.validity_date:
			self.validity_date = add_months(nowdate(), months)

	def validate_content(self):
		self.check_method_statement()
		self.check_area()
		assign_row_refs(self.steps, "step_ref", "S", _("Step"))
		self.check_works()
		self.check_hazard_links()
		self.check_validity()
		self.check_client_approval()

	# --- Checks ----------------------------------------------------------------------------------

	def check_works(self):
		seen = set()
		for row in self.works:
			if row.work in seen:
				frappe.throw(
					_("Row {0} of Works: {1} is listed more than once.").format(
						row.idx, frappe.bold(row.work)
					)
				)
			seen.add(row.work)

		if not self.method_statement:
			return

		allowed = set(frappe.get_doc("HSE Method Statement", self.method_statement).allowed_works())
		for row in self.works:
			if row.work not in allowed:
				frappe.throw(
					_(
						"Row {0} of Works: {1} is not a work of Method Statement {2}. Choose from: {3}."
					).format(
						row.idx,
						frappe.bold(row.work),
						frappe.bold(self.method_statement),
						", ".join(sorted(allowed)) or _("none"),
					)
				)

	def check_hazard_links(self):
		own_number = self.method_statement_number()
		for row in self.hazards:
			row.hira_line = (row.hira_line or "").strip() or None
			if row.hira_line and not row.hira:
				frappe.throw(
					_("Row {0} of Hazards: HIRA line {1} is given, but not the HIRA.").format(
						row.idx, frappe.bold(row.hira_line)
					)
				)
			if not row.hira:
				continue

			branch, method_statement = frappe.db.get_value(
				"HSE HIRA", row.hira, ["branch", "method_statement"]
			)
			if branch != self.branch:
				frappe.throw(
					_(
						"Row {0} of Hazards: HIRA {1} belongs to branch {2}, but this SOP is for branch {3}."
					).format(row.idx, frappe.bold(row.hira), frappe.bold(branch), frappe.bold(self.branch))
				)

			# Revisions of a Method Statement share its document number, so compare by that.
			their_number = self.method_statement_number(method_statement)
			if own_number and their_number and own_number != their_number:
				frappe.throw(
					_("Row {0} of Hazards: HIRA {1} is for Method Statement {2}, not for {3}.").format(
						row.idx,
						frappe.bold(row.hira),
						frappe.bold(method_statement),
						frappe.bold(self.method_statement),
					)
				)

			if row.hira_line:
				lines = frappe.get_all(
					"HSE HIRA Line", filters={"parent": row.hira, "parenttype": "HSE HIRA"}, pluck="line_ref"
				)
				if row.hira_line not in lines:
					frappe.throw(
						_("Row {0} of Hazards: HIRA {1} has no line {2}.").format(
							row.idx, frappe.bold(row.hira), frappe.bold(row.hira_line)
						)
					)

	def method_statement_number(self, method_statement=None):
		name = method_statement or self.method_statement
		return frappe.db.get_value("HSE Method Statement", name, "document_number") if name else None

	def check_validity(self):
		if not self.validity_date:
			return

		expired = getdate(self.validity_date) < getdate(nowdate())
		if expired and (self.is_new() or self.has_value_changed("validity_date")):
			frappe.throw(_("Valid Until cannot be in the past."))
		if expired and self.becoming_approved():
			frappe.throw(
				_("The validity date {0} has passed. Give a new Valid Until date before approving.").format(
					frappe.bold(self.validity_date)
				)
			)

	def check_client_approval(self):
		if not self.client_approval_required:
			return
		if self.client_approval_date and getdate(self.client_approval_date) > getdate(nowdate()):
			frappe.throw(_("Client Approval Date cannot be in the future."))
		if self.becoming_approved() and not (self.client_approval_reference and self.client_approval_date):
			frappe.throw(
				_(
					"This SOP needs the client's approval. Record the client's approval reference and date, save, then approve."
				),
				title=_("Client approval missing"),
			)

	def becoming_approved(self):
		before = self.get_doc_before_save()
		approved = get_approved_state()
		return self.workflow_state == approved and not (before and before.workflow_state == approved)

	# --- Ready for review ------------------------------------------------------------------------

	def review_problems(self):
		problems = []

		if not (self.purpose or "").strip():
			problems.append(_("Give the purpose of the SOP."))
		if not (self.scope or "").strip():
			problems.append(_("Give the scope of the SOP."))
		if self.method_statement and not self.works:
			problems.append(_("Choose the works of the Method Statement that this SOP covers."))
		if not self.steps:
			problems.append(_("Add at least one step to the procedure."))
		if not self.hazards:
			problems.append(
				_("List the hazards identified for the job, each with its risk mitigation action.")
			)
		if not self.validity_date:
			problems.append(_("Give the Valid Until date."))
		elif getdate(self.validity_date) < getdate(nowdate()):
			problems.append(_("The Valid Until date {0} has passed.").format(frappe.bold(self.validity_date)))

		return problems

	# --- When approved ---------------------------------------------------------------------------

	def on_update(self):
		super().on_update()
		if self.workflow_state == get_approved_state() and self.has_value_changed("workflow_state"):
			self.notify_distribution()

	def notify_distribution(self):
		"""Tell everyone on the distribution list that the SOP is issued or revised."""
		if self.previous_revision:
			subject = _("SOP {0} was revised (revision {1}): {2}").format(
				self.document_number, self.revision_number, self.sop_title
			)
		else:
			subject = _("SOP {0} was issued: {1}").format(self.document_number, self.sop_title)

		seen = set()
		for row in self.distribution:
			user = row.user
			if not user or user in seen or not frappe.db.get_value("User", user, "enabled"):
				continue
			seen.add(user)
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"type": "Alert",
					"subject": subject,
					"for_user": user,
					"from_user": frappe.session.user,
					"document_type": self.doctype,
					"document_name": self.name,
				}
			).insert(ignore_permissions=True)


def basic_ppe():
	"""The PPE every new SOP starts with: the items marked Basic in the PPE master."""
	return [
		{"ppe": item.name, "standard": item.standard}
		for item in frappe.get_all(
			"HSE PPE Item",
			filters={"is_basic": 1},
			fields=["name", "standard"],
			order_by="sort_order asc, name asc",
		)
	]


@frappe.whitelist()
def new_document_defaults():
	"""What a new SOP form starts with, so the screen shows it before the first save."""
	return {"basic_ppe": basic_ppe()}


@frappe.whitelist()
def hazards_from_hira(hira):
	"""Hazard rows for the SOP, made from a HIRA: one for each control measure of each line.

	A line with no control measure but an existing safeguard gives one row with that safeguard.
	A line with neither gives no row, as a hazard needs a mitigation action.
	"""
	frappe.has_permission("HSE HIRA", "read", doc=hira, throw=True)
	doc = frappe.get_doc("HSE HIRA", hira)

	rows = []
	for line in doc.lines:
		hazard = line.hazard
		if line.hazardous_event:
			hazard = f"{hazard} ({line.hazardous_event})"
		measures = [c.control for c in doc.controls if c.line_ref == line.line_ref and c.control]
		if not measures and line.existing_safeguard:
			measures = [line.existing_safeguard]
		for measure in measures:
			rows.append(
				{"hazard": hazard, "mitigation": measure, "hira": doc.name, "hira_line": line.line_ref}
			)
	return rows
