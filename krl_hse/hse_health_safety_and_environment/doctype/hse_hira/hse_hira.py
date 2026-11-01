import re

import frappe
from frappe import _

from krl_hse.utils.controlled_document import ControlledDocument, get_approved_state, get_settings
from krl_hse.utils.risk import severity_details, severity_for

LINE_REF = re.compile(r"^L(\d+)$")


class HSEHIRA(ControlledDocument):
	"""Hazard Identification and Risk Assessment, KRL/HSE/HIRA/1 (BRD 6.1.2).

	It belongs to a Method Statement. The rating of every line is worked out from the risk matrix,
	so the consequence and likelihood are what the officer chooses and the severity follows. A line
	whose severity stops work cannot be sent for review without a control measure.
	"""

	def before_insert(self):
		# Numbering needs the branch, and numbering comes before validation.
		self.fill_from_method_statement()

	def before_validate(self):
		self.fill_from_method_statement()

	def validate_content(self):
		self.check_method_statement()
		self.check_area()
		self.number_lines()
		self.rate_lines()
		self.check_controls()
		self.summarise_risk()

	# --- Method Statement ------------------------------------------------------------------------

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
				_("Method Statement {0} belongs to branch {1}, but this HIRA is for branch {2}.").format(
					frappe.bold(self.method_statement), frappe.bold(ms.branch), frappe.bold(self.branch)
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

		if not self.name_of_work:
			self.name_of_work = ms.name_of_work
		if not self.client_name:
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
					_("Choose the Method Statement this HIRA is for. A HIRA cannot be made on its own."),
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
				_("Method Statement {0} is {1}. A HIRA can only be made for an {2} Method Statement.").format(
					frappe.bold(self.method_statement),
					(state or _("not yet in any state")).lower(),
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
				_("Area {0} belongs to branch {1}, but this HIRA is for branch {2}.").format(
					frappe.bold(self.area), frappe.bold(branch), frappe.bold(self.branch)
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

	# --- Lines -----------------------------------------------------------------------------------

	def number_lines(self):
		"""Give each line a reference that stays with it when lines are moved or removed."""
		used = [row.line_ref for row in self.lines if row.line_ref]
		repeated = sorted({ref for ref in used if used.count(ref) > 1})
		if repeated:
			frappe.throw(_("Line {0} is used more than once.").format(", ".join(repeated)))

		numbers = [int(m.group(1)) for ref in used if (m := LINE_REF.match(ref))]
		following = max(numbers, default=0) + 1
		for row in self.lines:
			if not row.line_ref:
				row.line_ref = f"L{following}"
				following += 1

	def rate_lines(self):
		"""Fill probability and severity from the risk matrix, before and after the controls."""
		likelihood = {
			row.name: row.level for row in frappe.get_all("HSE Likelihood Level", fields=["name", "level"])
		}

		for row in self.lines:
			for prefix in ("", "residual_"):
				consequence = row.get(f"{prefix}consequence")
				chosen = row.get(f"{prefix}likelihood")
				row.set(f"{prefix}probability", likelihood.get(chosen, 0) if chosen else 0)

				severity = severity_for(consequence, chosen)
				if consequence and chosen and not severity:
					frappe.throw(
						_(
							"Row {0} of Lines: {1} with {2} has no severity in the risk matrix. Add it under HSE Risk Matrix."
						).format(row.idx, frappe.bold(consequence), frappe.bold(chosen))
					)
				row.set(f"{prefix}severity" if prefix == "" else "residual_severity", severity)

	def check_controls(self):
		refs = {row.line_ref for row in self.lines}
		for row in self.controls:
			if row.line_ref not in refs:
				frappe.throw(
					_(
						"Row {0} of Control Measures is for line {1}, which is not in the risk assessment."
					).format(row.idx, frappe.bold(row.line_ref))
				)

	def summarise_risk(self):
		"""Record the worst risk left after controls, for the list and the cross-site register."""
		details = severity_details()
		worst = None
		for row in self.lines:
			severity = row.residual_severity or row.severity
			if severity and (worst is None or details[severity]["level"] > details[worst]["level"]):
				worst = severity

		self.highest_residual_severity = worst
		self.has_high_residual_risk = 1 if worst and details[worst]["stops_work"] else 0

	# --- Ready for review ------------------------------------------------------------------------

	def review_problems(self):
		details = severity_details()
		problems = []

		if not self.lines:
			return [_("Add at least one line to the risk assessment.")]

		for row in self.lines:
			label = _("Line {0}").format(frappe.bold(row.line_ref or row.idx))
			if not (row.consequence and row.likelihood):
				problems.append(_("{0}: rate the consequence and likelihood.").format(label))
			if not (row.residual_consequence and row.residual_likelihood):
				problems.append(
					_(
						"{0}: rate the consequence and likelihood after the controls (the residual risk)."
					).format(label)
				)

			if row.severity and row.residual_severity:
				if details[row.residual_severity]["level"] > details[row.severity]["level"]:
					problems.append(
						_(
							"{0}: the risk after controls ({1}) is higher than before ({2}). Check the ratings."
						).format(label, row.residual_severity, row.severity)
					)

			if row.severity and details[row.severity]["stops_work"]:
				if not any(control.line_ref == row.line_ref for control in self.controls):
					problems.append(
						_("{0} is {1}, which stops work. Record at least one control measure for it.").format(
							label, frappe.bold(row.severity)
						)
					)

			if (
				get_settings().block_high_residual_risk
				and row.residual_severity
				and details[row.residual_severity]["stops_work"]
			):
				problems.append(
					_(
						"{0} is still {1} after the controls. Reduce the risk, or ask the HSE Head to change this setting."
					).format(label, frappe.bold(row.residual_severity))
				)

		for control in self.controls:
			if control.measure_type == "Additional" and not (control.responsible and control.target_date):
				problems.append(
					_(
						"Control measure {0} (line {1}) is an additional measure. Give who is responsible and the target date."
					).format(control.idx, control.line_ref)
				)

		return problems


@frappe.whitelist()
def method_statement_details(method_statement):
	"""What the form copies from the chosen Method Statement."""
	frappe.has_permission("HSE Method Statement", "read", doc=method_statement, throw=True)
	ms = frappe.get_doc("HSE Method Statement", method_statement)
	return {
		"branch": ms.branch,
		"work_order": ms.work_order,
		"name_of_work": ms.name_of_work,
		"client_name": ms.client_name,
		"areas": [row.area for row in ms.areas if row.area],
		"client_format_applies": ms.client_format_applies,
		"client_format_reference": ms.client_format_reference,
	}
