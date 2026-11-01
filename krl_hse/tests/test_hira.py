import frappe
from frappe.model.workflow import WorkflowPermissionError, WorkflowTransitionError
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, nowdate

from krl_hse.tests.utils import (
	act_on,
	current_fy,
	hira_line,
	make_approved_method_statement,
	make_area,
	make_branch,
	make_hira,
	make_method_statement,
	make_user,
	make_work_order,
	method_statement_content,
)
from krl_hse.utils.controlled_document import planning_rules, start_revision

DOMAIN = "krl-test.example"
CREATOR = f"test.hira_officer_t@{DOMAIN}"
REVIEWER = f"test.hira_bhse_t@{DOMAIN}"
APPROVER = f"test.hira_bhead_t@{DOMAIN}"

# Pairs in the starting risk matrix that give a work-stopping severity (IV and V).
STOPS_WORK = {"consequence": "C5 Catastrophic", "likelihood": "Certain"}


class HIRATestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_branch("TEST Athagarh", "T")
		make_branch("TEST Jharsuguda", "J")
		cls.order = make_work_order(
			"TEST Athagarh", "HIRA-WO", work_title="TEST Slag handling", client_name="TEST Client Metals"
		)
		cls.area = make_area("TEST Athagarh", "TEST LRF Pit", work_order=cls.order.name)
		make_user(CREATOR, ["HSE Officer"], branches=["TEST Athagarh"])
		make_user(REVIEWER, ["Branch HSE Head"], branches=["TEST Athagarh"])
		make_user(APPROVER, ["Branch Head"], branches=["TEST Athagarh"])

	def setUp(self):
		self.ms = make_approved_method_statement("TEST Athagarh", self.order.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def new_hira(self, **kw):
		kw.setdefault("area", self.area.name)
		return make_hira("TEST Athagarh", self.ms.name, **kw)

	def set_setting(self, fieldname, value):
		settings = frappe.get_doc("HSE Settings")
		original = settings.get(fieldname)
		settings.set(fieldname, value)
		settings.save(ignore_permissions=True)
		frappe.clear_cache(doctype="HSE Settings")

		def restore():
			again = frappe.get_doc("HSE Settings")
			again.set(fieldname, original)
			again.save(ignore_permissions=True)
			frappe.clear_cache(doctype="HSE Settings")

		self.addCleanup(restore)

	def submit(self, hira):
		return act_on(CREATOR, "HSE HIRA", hira.name, "Submit for Review")

	def approve(self, hira):
		act_on(CREATOR, "HSE HIRA", hira.name, "Submit for Review")
		act_on(REVIEWER, "HSE HIRA", hira.name, "Review and Forward")
		act_on(APPROVER, "HSE HIRA", hira.name, "Approve")
		frappe.set_user("Administrator")
		return frappe.get_doc("HSE HIRA", hira.name)


class TestNewHIRA(HIRATestCase):
	def test_number_and_starting_values(self):
		hira = self.new_hira()
		self.assertTrue(hira.name.startswith(f"KRL/HIRA/T/{current_fy()}/"), hira.name)
		self.assertEqual(hira.document_number, hira.name)
		self.assertEqual(hira.revision_number, 0)
		self.assertEqual(hira.workflow_state, "Draft")
		self.assertEqual([s.action for s in hira.sign_offs], ["Prepared"])

	def test_work_and_project_details_come_from_the_method_statement(self):
		hira = self.new_hira()
		self.assertEqual(hira.work_order, self.order.name)
		self.assertEqual(hira.name_of_work, "TEST Slag handling")
		self.assertEqual(hira.client_name, "TEST Client Metals")

	def test_branch_comes_from_the_method_statement_when_left_empty(self):
		hira = frappe.get_doc(
			{
				"doctype": "HSE HIRA",
				"method_statement": self.ms.name,
				"area": self.area.name,
				"lines": [hira_line()],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(hira.branch, "TEST Athagarh")

	def test_a_hira_cannot_be_made_without_a_method_statement(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "HSE HIRA",
					"branch": "TEST Athagarh",
					"area": self.area.name,
					"name_of_work": "x",
				}
			).insert(ignore_permissions=True)

	def test_the_method_statement_must_be_approved(self):
		draft = make_method_statement("TEST Athagarh", self.order.name, **method_statement_content())
		with self.assertRaises(frappe.ValidationError):
			make_hira("TEST Athagarh", draft.name, area=self.area.name)

	def test_the_rule_can_accept_a_method_statement_in_any_state(self):
		self.set_setting("parent_document_rule", "Any state")
		draft = make_method_statement("TEST Athagarh", self.order.name, **method_statement_content())
		hira = make_hira("TEST Athagarh", draft.name, area=self.area.name)
		self.assertEqual(hira.method_statement, draft.name)

	def test_the_rule_can_drop_the_method_statement(self):
		self.set_setting("parent_document_rule", "Not required")
		hira = frappe.get_doc(
			{
				"doctype": "HSE HIRA",
				"branch": "TEST Athagarh",
				"work_order": self.order.name,
				"area": self.area.name,
				"name_of_work": "TEST Stand-alone",
				"lines": [hira_line()],
			}
		).insert(ignore_permissions=True)
		self.assertFalse(hira.method_statement)

	def test_method_statement_must_be_in_the_same_branch(self):
		with self.assertRaises(frappe.ValidationError):
			make_hira("TEST Jharsuguda", self.ms.name)

	def test_area_must_be_in_the_same_branch(self):
		other = make_area("TEST Jharsuguda", "TEST Other Pit")
		with self.assertRaises(frappe.ValidationError):
			self.new_hira(area=other.name)

	def test_area_of_another_work_is_refused(self):
		other_order = make_work_order("TEST Athagarh", "HIRA-WO-2")
		stray = make_area("TEST Athagarh", "TEST Stray Pit", work_order=other_order.name)
		with self.assertRaises(frappe.ValidationError):
			self.new_hira(area=stray.name)

	def test_a_disabled_area_is_refused(self):
		off = make_area("TEST Athagarh", "TEST Closed Pit", disabled=1)
		with self.assertRaises(frappe.ValidationError):
			self.new_hira(area=off.name)

	def test_the_client_format_is_carried_from_the_method_statement(self):
		ms = make_approved_method_statement(
			"TEST Athagarh",
			self.order.name,
			client_format_applies=1,
			client_format_reference="CLIENT/HIRA/7",
		)
		hira = make_hira("TEST Athagarh", ms.name, area=self.area.name)
		self.assertEqual(hira.client_format_applies, 1)
		self.assertEqual(hira.client_format_reference, "CLIENT/HIRA/7")


class TestFormSettings(HIRATestCase):
	def test_the_form_gets_the_rule_and_the_approved_state(self):
		self.assertEqual(
			planning_rules(), {"parent_document_rule": "Approved only", "approved_state": "Approved"}
		)

	def test_a_changed_rule_reaches_the_form(self):
		self.set_setting("parent_document_rule", "Any state")
		self.assertEqual(planning_rules()["parent_document_rule"], "Any state")

	def test_an_officer_without_access_to_the_settings_still_gets_them(self):
		frappe.set_user(CREATOR)
		self.assertFalse(frappe.has_permission("HSE Settings", "read"))
		self.assertEqual(planning_rules()["approved_state"], "Approved")


class TestRatingLines(HIRATestCase):
	def test_lines_get_their_own_references(self):
		hira = self.new_hira(lines=[hira_line(), hira_line(), hira_line()])
		self.assertEqual([r.line_ref for r in hira.lines], ["L1", "L2", "L3"])

	def test_a_reference_stays_with_its_line_when_another_is_removed(self):
		hira = self.new_hira(lines=[hira_line(), hira_line(), hira_line()])
		hira.remove(hira.lines[0])
		hira.append("lines", hira_line())
		hira.save(ignore_permissions=True)
		self.assertEqual([r.line_ref for r in hira.lines], ["L2", "L3", "L4"])

	def test_a_reference_cannot_be_used_twice(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_hira(lines=[hira_line(line_ref="L1"), hira_line(line_ref="L1")])

	def test_severity_comes_from_the_matrix_before_and_after_controls(self):
		line = self.new_hira().lines[0]
		self.assertEqual((line.probability, line.severity), (3, "Severity III"))
		self.assertEqual((line.residual_probability, line.residual_severity), (1, "Severity I"))

	def test_the_worst_pair_is_severity_v(self):
		line = self.new_hira(lines=[hira_line(**STOPS_WORK)]).lines[0]
		self.assertEqual((line.probability, line.severity), (5, "Severity V"))

	def test_a_typed_severity_is_overwritten(self):
		line = self.new_hira(lines=[hira_line(severity="Severity V")]).lines[0]
		self.assertEqual(line.severity, "Severity III")

	def test_changing_the_rating_changes_the_severity(self):
		hira = self.new_hira()
		hira.lines[0].likelihood = "Certain"
		hira.save(ignore_permissions=True)
		self.assertEqual(hira.lines[0].severity, "Severity III")
		hira.lines[0].consequence = "C5 Catastrophic"
		hira.save(ignore_permissions=True)
		self.assertEqual(hira.lines[0].severity, "Severity V")

	def test_an_unrated_line_has_no_severity_but_can_be_saved_as_a_draft(self):
		hira = self.new_hira(lines=[hira_line(consequence="", likelihood="")])
		self.assertFalse(hira.lines[0].severity)
		self.assertEqual(hira.lines[0].probability, 0)

	def test_a_level_missing_from_the_matrix_is_refused(self):
		extra = frappe.get_doc(
			{"doctype": "HSE Likelihood Level", "likelihood_label": "TEST Extra", "level": 9}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "HSE Likelihood Level", extra.name, force=True)
		with self.assertRaises(frappe.ValidationError):
			self.new_hira(lines=[hira_line(likelihood=extra.name)])

	def test_the_matrix_decides_so_changing_it_changes_the_rating(self):
		matrix = frappe.get_doc("HSE Risk Matrix")
		original = [(r.consequence, r.likelihood, r.severity) for r in matrix.cells]

		def restore():
			again = frappe.get_doc("HSE Risk Matrix")
			again.cells = []
			for c, l, s in original:
				again.append("cells", {"consequence": c, "likelihood": l, "severity": s})
			again.save(ignore_permissions=True)

		self.addCleanup(restore)
		for row in matrix.cells:
			if (row.consequence, row.likelihood) == ("C2 Minor", "Possible"):
				row.severity = "Severity IV"
		matrix.save(ignore_permissions=True)

		self.assertEqual(self.new_hira().lines[0].severity, "Severity IV")

	def test_the_worst_risk_left_is_recorded(self):
		hira = self.new_hira(
			lines=[
				hira_line(),
				hira_line(**STOPS_WORK, residual_consequence="C3 Moderate", residual_likelihood="Possible"),
			]
		)
		self.assertEqual(hira.highest_residual_severity, "Severity III")
		self.assertEqual(hira.has_high_residual_risk, 0)

	def test_a_work_stopping_risk_after_controls_is_flagged(self):
		hira = self.new_hira(
			lines=[
				hira_line(
					**STOPS_WORK, residual_consequence="C5 Catastrophic", residual_likelihood="Very Likely"
				)
			]
		)
		self.assertEqual(hira.has_high_residual_risk, 1)

	def test_a_control_must_name_a_line_of_this_hira(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_hira(
				controls=[
					{"line_ref": "L9", "measure_type": "Existing", "control": "x", "hierarchy_level": "PPE"}
				]
			)


class TestReadyForReview(HIRATestCase):
	def problems(self, hira):
		return hira.review_problems()

	def test_a_complete_hira_can_be_sent(self):
		hira = self.new_hira()
		self.assertEqual(self.problems(hira), [])
		self.assertEqual(self.submit(hira).workflow_state, "Pending Branch HSE Head Review")

	def test_a_hira_without_lines_cannot_be_sent(self):
		hira = self.new_hira(lines=[])
		with self.assertRaises(frappe.ValidationError):
			self.submit(hira)

	def test_every_line_must_be_rated_before_and_after_the_controls(self):
		hira = self.new_hira(
			lines=[hira_line(consequence="", likelihood=""), hira_line(residual_likelihood="")]
		)
		self.assertEqual(len(self.problems(hira)), 2)
		with self.assertRaises(frappe.ValidationError):
			self.submit(hira)

	def test_a_work_stopping_line_needs_a_control_measure(self):
		hira = self.new_hira(lines=[hira_line(**STOPS_WORK)])
		self.assertTrue(any("stops work" in p for p in self.problems(hira)))
		with self.assertRaises(frappe.ValidationError):
			self.submit(hira)

	def test_a_control_for_the_line_clears_it(self):
		hira = self.new_hira(
			lines=[hira_line(**STOPS_WORK)],
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Existing",
					"control": "TEST barrier",
					"hierarchy_level": "Isolation",
				}
			],
		)
		self.assertEqual(self.problems(hira), [])

	def test_a_control_for_another_line_does_not_count(self):
		hira = self.new_hira(
			lines=[hira_line(), hira_line(**STOPS_WORK)],
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Existing",
					"control": "TEST barrier",
					"hierarchy_level": "Isolation",
				}
			],
		)
		self.assertEqual(len(self.problems(hira)), 1)

	def test_an_additional_measure_needs_who_and_when(self):
		hira = self.new_hira(
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Additional",
					"control": "TEST guard rail",
					"hierarchy_level": "Engineering Control",
				}
			]
		)
		self.assertEqual(len(self.problems(hira)), 1)

	def test_residual_risk_cannot_be_higher_than_the_initial_risk(self):
		hira = self.new_hira(
			lines=[hira_line(residual_consequence="C5 Catastrophic", residual_likelihood="Certain")]
		)
		self.assertTrue(any("higher than before" in p for p in self.problems(hira)))

	def test_a_work_stopping_residual_risk_is_allowed_by_default(self):
		hira = self.new_hira(
			lines=[
				hira_line(
					**STOPS_WORK, residual_consequence="C5 Catastrophic", residual_likelihood="Very Likely"
				)
			],
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Existing",
					"control": "TEST barrier",
					"hierarchy_level": "Isolation",
				}
			],
		)
		self.assertEqual(self.problems(hira), [])

	def test_the_setting_can_block_a_work_stopping_residual_risk(self):
		self.set_setting("block_high_residual_risk", 1)
		hira = self.new_hira(
			lines=[
				hira_line(
					**STOPS_WORK, residual_consequence="C5 Catastrophic", residual_likelihood="Very Likely"
				)
			],
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Existing",
					"control": "TEST barrier",
					"hierarchy_level": "Isolation",
				}
			],
		)
		self.assertEqual(len(self.problems(hira)), 1)
		self.assertIn("after the controls", self.problems(hira)[0])


class TestApprovalAndRevision(HIRATestCase):
	def test_the_approval_route(self):
		hira = self.new_hira()
		self.assertEqual(self.submit(hira).workflow_state, "Pending Branch HSE Head Review")
		act_on(REVIEWER, "HSE HIRA", hira.name, "Review and Forward")
		self.assertEqual(
			frappe.db.get_value("HSE HIRA", hira.name, "workflow_state"), "Pending Branch Head Approval"
		)
		act_on(APPROVER, "HSE HIRA", hira.name, "Approve")
		frappe.set_user("Administrator")
		approved = frappe.get_doc("HSE HIRA", hira.name)
		self.assertEqual(approved.workflow_state, "Approved")
		self.assertEqual(
			[s.action for s in approved.sign_offs],
			["Prepared", "Submit for Review", "Review and Forward", "Approve"],
		)

	def test_the_officer_cannot_approve(self):
		hira = self.new_hira()
		self.submit(hira)
		with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError)):
			act_on(CREATOR, "HSE HIRA", hira.name, "Review and Forward")

	def test_the_reviewer_cannot_give_the_final_approval(self):
		hira = self.new_hira()
		self.submit(hira)
		act_on(REVIEWER, "HSE HIRA", hira.name, "Review and Forward")
		with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError)):
			act_on(REVIEWER, "HSE HIRA", hira.name, "Approve")

	def test_sending_back_needs_recommendations(self):
		hira = self.new_hira()
		self.submit(hira)
		with self.assertRaises(frappe.ValidationError):
			act_on(REVIEWER, "HSE HIRA", hira.name, "Send Back")
		act_on(REVIEWER, "HSE HIRA", hira.name, "Send Back", recommendations="TEST: rate line L1 again")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("HSE HIRA", hira.name, "workflow_state"), "Sent Back")

	def test_approval_sets_the_issue_date_and_the_next_review(self):
		approved = self.approve(self.new_hira())
		self.assertEqual(str(approved.first_issue_date), nowdate())
		self.assertEqual(str(approved.next_review_date), str(add_months(nowdate(), 6)))

	def test_the_review_period_is_a_setting_of_the_document_code(self):
		settings = frappe.get_doc("HSE Settings")
		row = next(r for r in settings.document_codes if r.reference_doctype == "HSE HIRA")
		original = row.review_months
		row.review_months = 3
		settings.save(ignore_permissions=True)
		frappe.clear_cache(doctype="HSE Settings")

		def restore():
			again = frappe.get_doc("HSE Settings")
			next(
				r for r in again.document_codes if r.reference_doctype == "HSE HIRA"
			).review_months = original
			again.save(ignore_permissions=True)
			frappe.clear_cache(doctype="HSE Settings")

		self.addCleanup(restore)
		approved = self.approve(self.new_hira())
		self.assertEqual(str(approved.next_review_date), str(add_months(nowdate(), 3)))

	def test_no_review_date_when_the_period_is_zero(self):
		settings = frappe.get_doc("HSE Settings")
		row = next(r for r in settings.document_codes if r.reference_doctype == "HSE HIRA")
		original = row.review_months
		row.review_months = 0
		settings.save(ignore_permissions=True)
		frappe.clear_cache(doctype="HSE Settings")

		def restore():
			again = frappe.get_doc("HSE Settings")
			next(
				r for r in again.document_codes if r.reference_doctype == "HSE HIRA"
			).review_months = original
			again.save(ignore_permissions=True)
			frappe.clear_cache(doctype="HSE Settings")

		self.addCleanup(restore)
		self.assertFalse(self.approve(self.new_hira()).next_review_date)

	def test_an_approved_hira_cannot_be_edited_or_deleted(self):
		approved = self.approve(self.new_hira())
		approved.lines[0].hazard = "TEST changed"
		with self.assertRaises(frappe.ValidationError):
			approved.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("HSE HIRA", approved.name, force=True)

	def test_a_revision_keeps_the_lines_and_their_references(self):
		approved = self.approve(self.new_hira(lines=[hira_line(), hira_line()]))
		name = start_revision("HSE HIRA", approved.name, "CAPA Finding", "TEST: add a control")
		revision = frappe.get_doc("HSE HIRA", name)
		self.assertEqual(revision.name, f"{approved.name}-R1")
		self.assertEqual(revision.document_number, approved.name)
		self.assertEqual([r.line_ref for r in revision.lines], ["L1", "L2"])
		self.assertEqual(revision.workflow_state, "Draft")
		self.assertFalse(revision.next_review_date)

	def test_approving_a_revision_supersedes_the_earlier_one_and_restarts_the_review(self):
		approved = self.approve(self.new_hira())
		name = start_revision("HSE HIRA", approved.name, "CAPA Finding", "TEST: change")
		revision = self.approve(frappe.get_doc("HSE HIRA", name))
		self.assertEqual(frappe.db.get_value("HSE HIRA", approved.name, "workflow_state"), "Superseded")
		self.assertEqual(str(revision.revision_date), nowdate())
		self.assertEqual(str(revision.next_review_date), str(add_months(nowdate(), 6)))

	def test_a_revision_does_not_need_the_method_statement_to_still_be_approved(self):
		approved = self.approve(self.new_hira())
		frappe.db.set_value("HSE Method Statement", self.ms.name, "workflow_state", "Superseded")
		name = start_revision("HSE HIRA", approved.name, "CAPA Finding", "TEST: change")
		self.assertTrue(frappe.db.exists("HSE HIRA", name))
