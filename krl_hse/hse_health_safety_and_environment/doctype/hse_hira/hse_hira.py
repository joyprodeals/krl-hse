import frappe
from frappe import _

from krl_hse.utils.controlled_document import get_settings
from krl_hse.utils.planning_document import MethodStatementDocument, assign_row_refs
from krl_hse.utils.risk import severity_details, severity_for


class HSEHIRA(MethodStatementDocument):
	"""Hazard Identification and Risk Assessment, KRL/HSE/HIRA/1 (BRD 6.1.2).

	It belongs to a Method Statement. The rating of every line is worked out from the risk matrix,
	so the consequence and likelihood are what the officer chooses and the severity follows. A line
	whose severity stops work cannot be sent for review without a control measure.
	"""

	def validate_content(self):
		self.check_method_statement()
		self.check_area()
		assign_row_refs(self.lines, "line_ref", "L", _("Line"))
		self.rate_lines()
		self.check_controls()
		self.summarise_risk()

	# --- Lines -----------------------------------------------------------------------------------

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
