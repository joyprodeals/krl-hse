import frappe
from frappe import _
from frappe.utils import formatdate, getdate, nowdate

from krl_hse.utils.controlled_document import get_approved_state, get_settings
from krl_hse.utils.planning_document import MethodStatementDocument, assign_row_refs

ONE_PER_SOP = "One for each SOP"


class HSEJHA(MethodStatementDocument):
	"""Job Hazard Analysis, KRL/HSE/JHA/1 (BRD 6.1.4).

	A JHA is made for one SOP. Its steps come from the SOP, each step has one or more hazards, and
	each hazard has at least one control measure tagged to a level of the hierarchy of control. A new
	JHA goes through four approval levels, a revision through three (as the SOP does).
	"""

	# --- Filling in --------------------------------------------------------------------------------

	def before_insert(self):
		# Numbering needs the branch, and numbering comes before validation.
		self.fill_from_sop()
		super().before_insert()
		self.fill_from_sop_content()

	def before_validate(self):
		self.fill_from_sop()
		super().before_validate()

	def fill_from_sop(self):
		"""Take branch, Method Statement, work, area and title from the SOP."""
		if not self.sop:
			return

		sop = frappe.db.get_value(
			"HSE SOP",
			self.sop,
			["document_number", "branch", "method_statement", "work_order", "area", "sop_title"],
			as_dict=True,
		)
		if not sop:
			return

		self.sop_document_number = sop.document_number

		if not self.branch:
			self.branch = sop.branch
		elif sop.branch != self.branch:
			frappe.throw(
				_("SOP {0} belongs to branch {1}, but this JHA is for branch {2}.").format(
					frappe.bold(self.sop), frappe.bold(sop.branch), frappe.bold(self.branch)
				)
			)

		self.method_statement = sop.method_statement
		if not self.work_order:
			self.work_order = sop.work_order
		if not self.area:
			self.area = sop.area
		if not self.jha_title:
			self.jha_title = sop.sop_title

	def fill_from_sop_content(self):
		"""A new JHA starts with the steps and PPE of its SOP and the emergency numbers of the Method Statement.

		A revision already carries its own rows. The form shows the same rows before the first save.
		"""
		if self.previous_revision or not self.sop:
			return

		details = sop_details(self.sop, check_permission=False)
		if not self.steps:
			for step in details["steps"]:
				self.append("steps", step)
		if not self.ppe:
			for row in details["ppe"]:
				self.append("ppe", row)
		if not self.emergency_contacts:
			for row in details["contacts"]:
				self.append("emergency_contacts", row)

	# --- Checks ------------------------------------------------------------------------------------

	def validate_content(self):
		self.check_sop()
		self.check_one_per_sop()
		self.check_area()
		assign_row_refs(self.steps, "step_ref", "A", _("Step"))
		assign_row_refs(self.hazards, "hazard_ref", "H", _("Hazard"))
		self.check_steps()
		self.check_hazards()
		self.check_controls()
		self.check_people()
		self.check_reference_sops()

	def check_sop(self):
		"""A JHA is made for a SOP, and the SOP must be in force when it is chosen (HSE Settings)."""
		if not self.sop:
			frappe.throw(
				_("Choose the SOP this JHA is for. It cannot be made on its own."), title=_("SOP needed")
			)

		# A revision is a revision of the same JHA, so it stays with the same SOP, which may be a later
		# revision of it.
		if self.previous_revision:
			expected = frappe.db.get_value("HSE JHA", self.previous_revision, "sop_document_number")
			if expected and self.sop_document_number != expected:
				frappe.throw(
					_("This is a revision of a JHA for SOP {0}, so it must stay with that SOP.").format(
						frappe.bold(expected)
					)
				)
			if self.is_new() or not self.has_value_changed("sop"):
				return
		elif not (self.is_new() or self.has_value_changed("sop")):
			return

		if (get_settings().parent_document_rule or "Approved only") != "Approved only":
			return

		approved = get_approved_state()
		state, validity = frappe.db.get_value("HSE SOP", self.sop, ["workflow_state", "validity_date"])
		if state != approved:
			replacement = frappe.db.get_value(
				"HSE SOP",
				{"document_number": self.sop_document_number, "workflow_state": approved},
				"name",
			)
			frappe.throw(
				_("SOP {0} is {1}. A JHA can only be made for an {2} SOP.{3}").format(
					frappe.bold(self.sop),
					(state or _("not yet in any state")).lower(),
					approved.lower(),
					" " + _("Use {0}, which is in force.").format(frappe.bold(replacement))
					if replacement
					else "",
				),
				title=_("SOP not approved"),
			)
		if validity and getdate(validity) < getdate(nowdate()):
			frappe.throw(
				_(
					"SOP {0} expired on {1}. It must be reviewed and approved again before a JHA can be made for it."
				).format(frappe.bold(self.sop), frappe.bold(formatdate(validity))),
				title=_("SOP expired"),
			)

	def check_one_per_sop(self):
		if self.previous_revision or not self.sop_document_number:
			return
		if (get_settings().jha_per_sop or ONE_PER_SOP) != ONE_PER_SOP:
			return
		if not (self.is_new() or self.has_value_changed("sop")):
			return

		other = frappe.db.get_value(
			"HSE JHA",
			{
				"sop_document_number": self.sop_document_number,
				"document_number": ["!=", self.document_number or ""],
			},
			"name",
		)
		if other:
			frappe.throw(
				_(
					"SOP {0} already has JHA {1}. A SOP has one JHA: change it with Revision, Start Revision."
				).format(frappe.bold(self.sop_document_number), frappe.bold(other)),
				title=_("JHA already exists"),
			)

	def check_steps(self):
		if not self.sop:
			return
		sop_refs = set(
			frappe.get_all(
				"HSE SOP Step", filters={"parent": self.sop, "parenttype": "HSE SOP"}, pluck="step_ref"
			)
		)
		for row in self.steps:
			row.sop_step_ref = (row.sop_step_ref or "").strip() or None
			if row.sop_step_ref and row.sop_step_ref not in sop_refs:
				frappe.throw(
					_("Row {0} of Steps: SOP {1} has no step {2}.").format(
						row.idx, frappe.bold(self.sop), frappe.bold(row.sop_step_ref)
					)
				)

	def check_hazards(self):
		step_refs = {row.step_ref for row in self.steps}
		own_number = self.method_statement_number()

		for row in self.hazards:
			if row.step_ref not in step_refs:
				frappe.throw(
					_("Row {0} of Hazards: step {1} is not one of the steps of this JHA.").format(
						row.idx, frappe.bold(row.step_ref or "")
					)
				)

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
						"Row {0} of Hazards: HIRA {1} belongs to branch {2}, but this JHA is for branch {3}."
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

	def check_controls(self):
		refs = {row.hazard_ref for row in self.hazards}
		for row in self.controls:
			if row.hazard_ref not in refs:
				frappe.throw(
					_(
						"Row {0} of Control Measures is for hazard {1}, which is not one of the hazards of this JHA."
					).format(row.idx, frappe.bold(row.hazard_ref or ""))
				)

	def check_people(self):
		for fieldname, label in (
			("analysis_team", _("Hazard Analysis Team")),
			("employees_consulted", _("Employees Consulted")),
		):
			for row in self.get(fieldname):
				if row.employee and not row.person_name:
					row.person_name = frappe.db.get_value("Employee", row.employee, "employee_name")
				if not row.person_name:
					frappe.throw(
						_("Row {0} of {1}: give the name, or choose the employee.").format(row.idx, label)
					)

	def check_reference_sops(self):
		seen = set()
		for row in self.reference_sops:
			if not (row.sop or (row.reference or "").strip()):
				frappe.throw(
					_("Row {0} of Reference SOPs: choose the SOP, or give its reference.").format(row.idx)
				)
			key = row.sop or row.reference.strip()
			if row.sop and row.sop == self.sop:
				frappe.throw(
					_(
						"Row {0} of Reference SOPs: {1} is the SOP this JHA is for, which is always listed first."
					).format(row.idx, frappe.bold(row.sop))
				)
			if key in seen:
				frappe.throw(
					_("Row {0} of Reference SOPs: {1} is listed more than once.").format(
						row.idx, frappe.bold(key)
					)
				)
			seen.add(key)

	def status_notice(self):
		"""Say so when the SOP this JHA was made for has been replaced, has expired or is not in force."""
		if not self.sop or not frappe.db.exists("HSE SOP", self.sop):
			return ""
		return sop_notice(frappe.get_doc("HSE SOP", self.sop))

	# --- Ready for review --------------------------------------------------------------------------

	def review_problems(self):
		problems = []

		if not self.steps:
			problems.append(_("Add at least one step to the job."))
		if not self.analysis_team:
			problems.append(_("Name the hazard analysis team."))

		hazards_of = {}
		for hazard in self.hazards:
			hazards_of.setdefault(hazard.step_ref, []).append(hazard)
		controls_of = {}
		for control in self.controls:
			controls_of.setdefault(control.hazard_ref, []).append(control)

		for step in self.steps:
			if not hazards_of.get(step.step_ref):
				problems.append(
					_("Step {0} has no hazard. Identify the hazards of every step.").format(
						frappe.bold(step.step_ref or step.idx)
					)
				)

		for hazard in self.hazards:
			label = _("Hazard {0} (step {1})").format(
				frappe.bold(hazard.hazard_ref or hazard.idx), hazard.step_ref
			)
			if not (hazard.impact or "").strip():
				problems.append(_("{0}: describe the impact of the hazard.").format(label))
			controls = controls_of.get(hazard.hazard_ref, [])
			if not controls:
				problems.append(_("{0} needs at least one control measure.").format(label))
			for control in controls:
				if not control.hierarchy_level:
					problems.append(
						_("{0}: tag control measure {1} to a level of the hierarchy of control.").format(
							label, control.idx
						)
					)

		return problems


# --- What the form takes from the SOP and the HIRA ---------------------------------------------------


def sop_details(sop, check_permission=True):
	"""What a JHA takes from its SOP: title, steps, PPE and the emergency numbers of its Method Statement.

	`notice` says why the SOP can no longer be relied on (replaced, expired, not approved), if so.
	"""
	if check_permission:
		frappe.has_permission("HSE SOP", "read", doc=sop, throw=True)

	doc = frappe.get_doc("HSE SOP", sop)
	approved = get_approved_state()

	contacts = []
	if doc.method_statement:
		contacts = [
			{"contact_type": row.contact_type, "phone": row.phone, "details": row.details}
			for row in frappe.get_all(
				"HSE MS Emergency Number",
				filters={"parent": doc.method_statement, "parenttype": "HSE Method Statement"},
				fields=["contact_type", "phone", "details"],
				order_by="idx",
			)
		]

	return {
		"title": doc.sop_title,
		"document_number": doc.document_number,
		"revision_number": doc.revision_number,
		"branch": doc.branch,
		"method_statement": doc.method_statement,
		"work_order": doc.work_order,
		"area": doc.area,
		"name_of_work": doc.name_of_work,
		"client_name": doc.client_name,
		"state": doc.workflow_state,
		"validity_date": str(doc.validity_date) if doc.validity_date else None,
		"notice": sop_notice(doc, approved),
		"steps": [{"activity": row.activity, "sop_step_ref": row.step_ref} for row in doc.steps],
		"ppe": [{"ppe": row.ppe, "standard": row.standard} for row in doc.ppe],
		"contacts": contacts,
	}


def sop_notice(sop, approved=None):
	"""Why a SOP can no longer be relied on, or an empty string when it is in force."""
	approved = approved or get_approved_state()
	if sop.workflow_state != approved:
		replacement = frappe.db.get_value(
			"HSE SOP", {"document_number": sop.document_number, "workflow_state": approved}, "name"
		)
		if replacement and replacement != sop.name:
			return _("SOP {0} has been replaced by {1}. Check this JHA against it.").format(
				sop.name, replacement
			)
		return _("SOP {0} is {1}, not in force.").format(sop.name, (sop.workflow_state or "").lower())
	if sop.validity_date and getdate(sop.validity_date) < getdate(nowdate()):
		return _("SOP {0} expired on {1}. Check this JHA when the SOP is approved again.").format(
			sop.name, formatdate(sop.validity_date)
		)
	return ""


@frappe.whitelist()
def get_sop_details(sop):
	return sop_details(sop)


@frappe.whitelist()
def hira_lines(hira):
	"""The lines of a HIRA, for choosing which hazards to copy into the JHA."""
	frappe.has_permission("HSE HIRA", "read", doc=hira, throw=True)
	doc = frappe.get_doc("HSE HIRA", hira)
	return [
		{"line_ref": line.line_ref, "activity": line.activity, "hazard": line.hazard} for line in doc.lines
	]


@frappe.whitelist()
def hazards_from_hira(hira, lines=None):
	"""Hazard rows for the JHA, made from lines of a HIRA, each with its control measures.

	`lines` is the references of the lines to copy (all when empty). A line with no control measure
	but an existing safeguard gets one control measure from it, with no level, which the officer
	then tags. Returns a list of {hazard: {...}, controls: [{...}]}.
	"""
	frappe.has_permission("HSE HIRA", "read", doc=hira, throw=True)
	chosen = frappe.parse_json(lines) if isinstance(lines, str) else lines
	doc = frappe.get_doc("HSE HIRA", hira)

	result = []
	for line in doc.lines:
		if chosen and line.line_ref not in chosen:
			continue

		controls = [
			{"control": c.control, "hierarchy_level": c.hierarchy_level}
			for c in doc.controls
			if c.line_ref == line.line_ref and c.control
		]
		if not controls and line.existing_safeguard:
			controls = [{"control": line.existing_safeguard, "hierarchy_level": None}]

		result.append(
			{
				"hazard": {
					"hazard": line.hazard,
					"impact": line.consequence_impact or line.hazardous_event or "",
					"source": line.hazard_category,
					"cause": line.cause,
					"trigger_condition": line.hazardous_event,
					"hira": doc.name,
					"hira_line": line.line_ref,
				},
				"controls": controls,
			}
		)
	return result
