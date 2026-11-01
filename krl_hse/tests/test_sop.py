import frappe
from frappe.model.workflow import WorkflowPermissionError, WorkflowTransitionError
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, nowdate

from krl_hse.hse_health_safety_and_environment.doctype.hse_sop.hse_sop import hazards_from_hira
from krl_hse.tests.utils import (
	act_on,
	current_fy,
	hira_line,
	make_approved_method_statement,
	make_area,
	make_branch,
	make_hira,
	make_method_statement,
	make_sop,
	make_user,
	make_work_order,
	method_statement_content,
	override_review_months,
	override_setting,
	sop_content,
	sop_step,
)
from krl_hse.utils.controlled_document import start_revision

DOMAIN = "krl-test.example"
CREATOR = f"test.sop_officer_t@{DOMAIN}"
REVIEWER = f"test.sop_bhse_t@{DOMAIN}"
BRANCH_HEAD = f"test.sop_bhead_t@{DOMAIN}"
HO_TEAM = f"test.sop_ho@{DOMAIN}"
LISTED = f"test.sop_listed@{DOMAIN}"
SPARE = f"test.sop_spare@{DOMAIN}"

DOCTYPE = "HSE SOP"


class SOPTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_branch("TEST Athagarh", "T")
		make_branch("TEST Jharsuguda", "J")
		cls.order = make_work_order(
			"TEST Athagarh", "SOP-WO", work_title="TEST Slag handling", client_name="TEST Client Metals"
		)
		cls.area = make_area("TEST Athagarh", "TEST SOP Pit", work_order=cls.order.name)
		make_user(CREATOR, ["HSE Officer"], branches=["TEST Athagarh"])
		make_user(REVIEWER, ["Branch HSE Head"], branches=["TEST Athagarh"])
		make_user(BRANCH_HEAD, ["Branch Head"], branches=["TEST Athagarh"])
		make_user(HO_TEAM, ["HO HSE Team"])
		make_user(LISTED, ["Site Supervisor"], branches=["TEST Athagarh"])
		make_user(SPARE, ["Site Supervisor"], branches=["TEST Athagarh"])

	def setUp(self):
		self.ms = make_approved_method_statement("TEST Athagarh", self.order.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def new_sop(self, **kw):
		return make_sop("TEST Athagarh", self.ms.name, **kw)

	def problems(self, sop):
		return sop.review_problems()

	def state(self, sop):
		return frappe.db.get_value(DOCTYPE, sop.name, "workflow_state")

	def go_to_ho(self, sop):
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		act_on(REVIEWER, DOCTYPE, sop.name, "Review and Forward")
		act_on(BRANCH_HEAD, DOCTYPE, sop.name, "Approve and Forward")

	def approve(self, sop):
		self.go_to_ho(sop)
		act_on(HO_TEAM, DOCTYPE, sop.name, "Approve")
		frappe.set_user("Administrator")
		return frappe.get_doc(DOCTYPE, sop.name)

	def approve_revision(self, sop):
		"""A revision skips the Branch HSE Head step."""
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		act_on(BRANCH_HEAD, DOCTYPE, sop.name, "Approve and Forward")
		act_on(HO_TEAM, DOCTYPE, sop.name, "Approve")
		frappe.set_user("Administrator")
		return frappe.get_doc(DOCTYPE, sop.name)


class TestNewSOP(SOPTestCase):
	def test_number_and_starting_values(self):
		sop = self.new_sop()
		self.assertTrue(sop.name.startswith(f"KRL/SOP/T/{current_fy()}/"), sop.name)
		self.assertEqual(sop.document_number, sop.name)
		self.assertEqual(sop.revision_number, 0)
		self.assertEqual(sop.workflow_state, "Draft")
		self.assertEqual([s.action for s in sop.sign_offs], ["Prepared"])

	def test_work_and_project_details_come_from_the_method_statement(self):
		sop = self.new_sop()
		self.assertEqual(sop.work_order, self.order.name)
		self.assertEqual(sop.name_of_work, "TEST Slag handling")
		self.assertEqual(sop.client_name, "TEST Client Metals")

	def test_the_basic_ppe_starts_filled(self):
		sop = self.new_sop()
		basic = frappe.get_all("HSE PPE Item", filters={"is_basic": 1}, pluck="name")
		self.assertTrue(basic)
		self.assertEqual(sorted(row.ppe for row in sop.ppe), sorted(basic))

	def test_typed_ppe_is_not_replaced_by_the_basic_set(self):
		item = frappe.get_all("HSE PPE Item", pluck="name", limit=1)[0]
		sop = self.new_sop(ppe=[{"ppe": item}])
		self.assertEqual([row.ppe for row in sop.ppe], [item])

	def test_a_sop_cannot_be_made_without_a_method_statement(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": DOCTYPE, "branch": "TEST Athagarh", **sop_content(works=[])}).insert(
				ignore_permissions=True
			)

	def test_the_method_statement_must_be_approved(self):
		draft = make_method_statement("TEST Athagarh", self.order.name, **method_statement_content())
		with self.assertRaises(frappe.ValidationError):
			make_sop("TEST Athagarh", draft.name)

	def test_the_rule_can_drop_the_method_statement(self):
		self.addCleanup(override_setting("parent_document_rule", "Not required"))
		sop = frappe.get_doc({"doctype": DOCTYPE, "branch": "TEST Athagarh", **sop_content(works=[])}).insert(
			ignore_permissions=True
		)
		self.assertFalse(sop.method_statement)

	def test_method_statement_must_be_in_the_same_branch(self):
		with self.assertRaises(frappe.ValidationError):
			make_sop("TEST Jharsuguda", self.ms.name)

	def test_steps_get_their_own_references(self):
		sop = self.new_sop(steps=[sop_step(), sop_step(), sop_step()])
		self.assertEqual([r.step_ref for r in sop.steps], ["S1", "S2", "S3"])

	def test_a_reference_stays_with_its_step_when_another_is_removed(self):
		sop = self.new_sop(steps=[sop_step(), sop_step(), sop_step()])
		sop.remove(sop.steps[0])
		sop.append("steps", sop_step())
		sop.save(ignore_permissions=True)
		self.assertEqual([r.step_ref for r in sop.steps], ["S2", "S3", "S4"])

	def test_a_step_reference_cannot_be_used_twice(self):
		sop = self.new_sop(steps=[sop_step(), sop_step()])
		sop.steps[1].step_ref = "S1"
		with self.assertRaises(frappe.ValidationError):
			sop.save(ignore_permissions=True)


class TestWorksAndHazards(SOPTestCase):
	def test_a_work_must_belong_to_the_method_statement(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_sop(works=[{"work": "TEST Some other work"}])

	def test_a_common_work_is_accepted(self):
		sop = self.new_sop(works=[{"work": "General"}])
		self.assertEqual([r.work for r in sop.works], ["General"])

	def test_a_work_is_listed_once(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_sop(works=[{"work": "TEST Slag handling"}, {"work": "TEST Slag handling"}])

	def test_a_hazard_can_be_linked_to_a_line_of_a_hira(self):
		hira = make_hira("TEST Athagarh", self.ms.name, area=self.area.name)
		sop = self.new_sop(
			hazards=[{"hazard": "TEST h", "mitigation": "TEST m", "hira": hira.name, "hira_line": "L1"}]
		)
		self.assertEqual(sop.hazards[0].hira_line, "L1")

	def test_a_line_that_the_hira_does_not_have_is_refused(self):
		hira = make_hira("TEST Athagarh", self.ms.name, area=self.area.name)
		with self.assertRaises(frappe.ValidationError):
			self.new_sop(
				hazards=[{"hazard": "TEST h", "mitigation": "TEST m", "hira": hira.name, "hira_line": "L9"}]
			)

	def test_a_line_without_a_hira_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_sop(hazards=[{"hazard": "TEST h", "mitigation": "TEST m", "hira_line": "L1"}])

	def test_a_hira_of_another_method_statement_is_refused(self):
		other = make_approved_method_statement("TEST Athagarh", self.order.name)
		hira = make_hira("TEST Athagarh", other.name, area=self.area.name)
		with self.assertRaises(frappe.ValidationError):
			self.new_sop(hazards=[{"hazard": "TEST h", "mitigation": "TEST m", "hira": hira.name}])

	def test_hazards_come_from_the_hira_with_their_control_measures(self):
		hira = make_hira(
			"TEST Athagarh",
			self.ms.name,
			area=self.area.name,
			lines=[
				hira_line(hazard="TEST: loader near people", existing_safeguard="TEST: banksman"),
				hira_line(hazard="TEST: hot slag"),
				hira_line(hazard="TEST: nothing recorded"),
			],
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Additional",
					"control": "TEST: barricade the lane",
					"hierarchy_level": "Isolation",
					"responsible": None,
				},
				{
					"line_ref": "L2",
					"measure_type": "Existing",
					"control": "TEST: face shield",
					"hierarchy_level": "PPE",
				},
			],
		)
		rows = hazards_from_hira(hira.name)
		self.assertEqual(
			[(r["hira_line"], r["mitigation"]) for r in rows],
			[("L1", "TEST: barricade the lane"), ("L2", "TEST: face shield")],
		)
		self.assertTrue(all(r["hira"] == hira.name for r in rows))

	def test_a_line_with_only_an_existing_safeguard_gives_that_as_the_action(self):
		hira = make_hira(
			"TEST Athagarh",
			self.ms.name,
			area=self.area.name,
			lines=[hira_line(hazard="TEST: loader near people", existing_safeguard="TEST: banksman")],
		)
		rows = hazards_from_hira(hira.name)
		self.assertEqual([r["mitigation"] for r in rows], ["TEST: banksman"])
		self.assertIn("TEST: loader near people", rows[0]["hazard"])


class TestValidityAndClientApproval(SOPTestCase):
	def test_the_validity_date_cannot_be_in_the_past(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_sop(validity_date=add_days(nowdate(), -1))

	def test_a_draft_can_be_saved_without_a_validity_date_but_not_sent(self):
		sop = self.new_sop(validity_date=None)
		self.assertTrue(any("Valid Until" in p for p in self.problems(sop)))
		with self.assertRaises(frappe.ValidationError):
			act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")

	def test_a_validity_date_that_has_since_passed_blocks_sending(self):
		sop = self.new_sop()
		frappe.db.set_value(DOCTYPE, sop.name, "validity_date", add_days(nowdate(), -3))
		sop.reload()
		self.assertTrue(any("passed" in p for p in self.problems(sop)))

	def test_a_validity_date_that_passes_while_in_review_blocks_approval(self):
		sop = self.new_sop()
		self.go_to_ho(sop)
		frappe.db.set_value(DOCTYPE, sop.name, "validity_date", add_days(nowdate(), -1))
		with self.assertRaises(frappe.ValidationError):
			act_on(HO_TEAM, DOCTYPE, sop.name, "Approve")

	def test_the_validity_date_is_prefilled_from_the_review_period_when_one_is_set(self):
		self.addCleanup(override_review_months("HSE SOP", 12))
		sop = self.new_sop(validity_date=None)
		self.assertEqual(str(sop.validity_date), str(add_months(nowdate(), 12)))

	def test_no_prefill_when_the_review_period_is_zero(self):
		sop = self.new_sop(validity_date=None)
		self.assertFalse(sop.validity_date)

	def test_client_approval_must_be_recorded_before_approval_when_required(self):
		sop = self.new_sop(client_approval_required=1)
		self.go_to_ho(sop)
		with self.assertRaises(frappe.ValidationError):
			act_on(HO_TEAM, DOCTYPE, sop.name, "Approve")
		act_on(
			HO_TEAM,
			DOCTYPE,
			sop.name,
			"Approve",
			client_approval_reference="TEST/CLIENT/77",
			client_approval_date=nowdate(),
		)
		self.assertEqual(self.state(sop), "Approved")

	def test_client_approval_is_not_needed_when_not_required(self):
		self.assertEqual(self.approve(self.new_sop()).workflow_state, "Approved")

	def test_client_approval_date_cannot_be_in_the_future(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_sop(
				client_approval_required=1,
				client_approval_reference="TEST/1",
				client_approval_date=add_days(nowdate(), 2),
			)


class TestReadyForReview(SOPTestCase):
	def test_a_complete_sop_can_be_sent(self):
		sop = self.new_sop()
		self.assertEqual(self.problems(sop), [])
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		self.assertEqual(self.state(sop), "Pending Branch HSE Head Review")

	def test_each_missing_part_is_named(self):
		sop = self.new_sop(purpose="", scope="", steps=[], hazards=[], works=[], validity_date=None)
		text = " ".join(self.problems(sop))
		for part in ("purpose", "scope", "works", "step", "hazards", "Valid Until"):
			self.assertIn(part, text)
		with self.assertRaises(frappe.ValidationError):
			act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")

	def test_a_sop_without_works_is_incomplete_when_it_belongs_to_a_method_statement(self):
		sop = self.new_sop(works=[])
		self.assertEqual(len(self.problems(sop)), 1)
		self.assertIn("works", self.problems(sop)[0])


class TestApprovalRoute(SOPTestCase):
	def test_a_new_sop_goes_through_four_levels(self):
		sop = self.new_sop()
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		self.assertEqual(self.state(sop), "Pending Branch HSE Head Review")
		act_on(REVIEWER, DOCTYPE, sop.name, "Review and Forward")
		self.assertEqual(self.state(sop), "Pending Branch Head Approval")
		act_on(BRANCH_HEAD, DOCTYPE, sop.name, "Approve and Forward")
		self.assertEqual(self.state(sop), "Pending HO HSE Team Approval")
		act_on(HO_TEAM, DOCTYPE, sop.name, "Approve")
		frappe.set_user("Administrator")
		approved = frappe.get_doc(DOCTYPE, sop.name)
		self.assertEqual(approved.workflow_state, "Approved")
		self.assertEqual(
			[s.action for s in approved.sign_offs],
			["Prepared", "Submit for Review", "Review and Forward", "Approve and Forward", "Approve"],
		)

	def test_a_level_cannot_be_skipped_by_the_wrong_role(self):
		sop = self.new_sop()
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		for user, action in (
			(CREATOR, "Review and Forward"),
			(BRANCH_HEAD, "Review and Forward"),
			(HO_TEAM, "Approve and Forward"),
			(HO_TEAM, "Approve"),
		):
			with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError), msg=(user, action)):
				act_on(user, DOCTYPE, sop.name, action)

	def test_the_branch_head_cannot_give_the_final_approval(self):
		sop = self.new_sop()
		self.go_to_ho(sop)
		with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError)):
			act_on(BRANCH_HEAD, DOCTYPE, sop.name, "Approve")
		with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError)):
			act_on(REVIEWER, DOCTYPE, sop.name, "Approve")

	def test_sending_back_needs_recommendations_at_every_level(self):
		for stop in ("review", "branch_head", "ho"):
			sop = self.new_sop()
			act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
			who = REVIEWER
			if stop in ("branch_head", "ho"):
				act_on(REVIEWER, DOCTYPE, sop.name, "Review and Forward")
				who = BRANCH_HEAD
			if stop == "ho":
				act_on(BRANCH_HEAD, DOCTYPE, sop.name, "Approve and Forward")
				who = HO_TEAM
			with self.assertRaises(frappe.ValidationError, msg=stop):
				act_on(who, DOCTYPE, sop.name, "Send Back")
			act_on(who, DOCTYPE, sop.name, "Send Back", recommendations="TEST: add the isolation step")
			frappe.set_user("Administrator")
			self.assertEqual(self.state(sop), "Sent Back", stop)

	def test_a_sent_back_new_sop_starts_the_route_again(self):
		sop = self.new_sop()
		self.go_to_ho(sop)
		act_on(HO_TEAM, DOCTYPE, sop.name, "Send Back", recommendations="TEST: fix")
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		self.assertEqual(self.state(sop), "Pending Branch HSE Head Review")

	def test_approval_sets_the_issue_date(self):
		approved = self.approve(self.new_sop())
		self.assertEqual(str(approved.first_issue_date), nowdate())
		self.assertFalse(approved.revision_date)

	def test_an_approved_sop_cannot_be_edited_or_deleted(self):
		approved = self.approve(self.new_sop())
		approved.purpose = "TEST changed"
		with self.assertRaises(frappe.ValidationError):
			approved.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(DOCTYPE, approved.name, force=True)


class TestRevision(SOPTestCase):
	def revise(self, sop):
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, sop.name, "CAPA Finding", "TEST: add a step")
		frappe.set_user("Administrator")
		return frappe.get_doc(DOCTYPE, name)

	def test_a_revision_keeps_the_content_and_step_references(self):
		approved = self.approve(self.new_sop(steps=[sop_step(), sop_step()]))
		revision = self.revise(approved)
		self.assertEqual(revision.name, f"{approved.name}-R1")
		self.assertEqual(revision.document_number, approved.name)
		self.assertEqual([r.step_ref for r in revision.steps], ["S1", "S2"])
		self.assertEqual(revision.purpose, approved.purpose)
		self.assertEqual(revision.workflow_state, "Draft")

	def test_a_revision_needs_a_new_validity_date(self):
		revision = self.revise(self.approve(self.new_sop()))
		self.assertFalse(revision.validity_date)
		self.assertTrue(any("Valid Until" in p for p in self.problems(revision)))

	def test_a_revision_goes_straight_to_the_branch_head(self):
		revision = self.revise(self.approve(self.new_sop()))
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		act_on(CREATOR, DOCTYPE, revision.name, "Submit for Review")
		self.assertEqual(self.state(revision), "Pending Branch Head Approval")

	def test_the_revision_has_three_levels(self):
		revision = self.revise(self.approve(self.new_sop()))
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		approved = self.approve_revision(revision)
		self.assertEqual(approved.workflow_state, "Approved")
		self.assertEqual(
			[s.action for s in approved.sign_offs],
			["Prepared", "Submit for Review", "Approve and Forward", "Approve"],
		)

	def test_the_branch_hse_head_does_not_review_a_revision(self):
		revision = self.revise(self.approve(self.new_sop()))
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		act_on(CREATOR, DOCTYPE, revision.name, "Submit for Review")
		with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError)):
			act_on(REVIEWER, DOCTYPE, revision.name, "Review and Forward")

	def test_a_sent_back_revision_returns_to_the_short_route(self):
		revision = self.revise(self.approve(self.new_sop()))
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		act_on(CREATOR, DOCTYPE, revision.name, "Submit for Review")
		act_on(BRANCH_HEAD, DOCTYPE, revision.name, "Send Back", recommendations="TEST: fix")
		act_on(CREATOR, DOCTYPE, revision.name, "Submit for Review")
		self.assertEqual(self.state(revision), "Pending Branch Head Approval")

	def test_approving_a_revision_supersedes_the_earlier_one(self):
		approved = self.approve(self.new_sop())
		revision = self.revise(approved)
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		revision = self.approve_revision(revision)
		self.assertEqual(frappe.db.get_value(DOCTYPE, approved.name, "workflow_state"), "Superseded")
		self.assertEqual(str(revision.revision_date), nowdate())

	def test_the_earlier_revision_stays_in_force_until_the_new_one_is_approved(self):
		approved = self.approve(self.new_sop())
		self.revise(approved)
		self.assertEqual(frappe.db.get_value(DOCTYPE, approved.name, "workflow_state"), "Approved")


class TestDistribution(SOPTestCase):
	def notices(self, sop, user):
		return frappe.get_all(
			"Notification Log",
			filters={"document_type": DOCTYPE, "document_name": sop.name, "for_user": user},
			pluck="subject",
		)

	def distribution(self):
		return [
			{"recipient": "TEST Stores", "user": LISTED, "copies": 1},
			{"recipient": "TEST Stores again", "user": LISTED, "copies": 1},
			{"recipient": "TEST Paper copy only", "copies": 2},
		]

	def test_nobody_is_told_before_approval(self):
		sop = self.new_sop(distribution=self.distribution())
		self.go_to_ho(sop)
		self.assertEqual(self.notices(sop, LISTED), [])

	def test_the_distribution_list_is_told_when_the_sop_is_issued(self):
		sop = self.approve(self.new_sop(distribution=self.distribution()))
		notices = self.notices(sop, LISTED)
		self.assertEqual(len(notices), 1)
		self.assertIn("issued", notices[0])
		self.assertIn(sop.document_number, notices[0])
		self.assertEqual(self.notices(sop, SPARE), [])

	def test_a_revision_is_announced_as_a_revision(self):
		approved = self.approve(self.new_sop(distribution=self.distribution()))
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, approved.name, "CAPA Finding", "TEST: change")
		frappe.set_user("Administrator")
		revision = frappe.get_doc(DOCTYPE, name)
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		self.approve_revision(revision)
		notices = self.notices(revision, LISTED)
		self.assertEqual(len(notices), 1)
		self.assertIn("revised", notices[0])
		self.assertIn("revision 1", notices[0])

	def test_a_disabled_user_is_skipped(self):
		frappe.db.set_value("User", SPARE, "enabled", 0)
		self.addCleanup(frappe.db.set_value, "User", SPARE, "enabled", 1)
		sop = self.approve(self.new_sop(distribution=[{"recipient": "TEST Spare", "user": SPARE}]))
		self.assertEqual(self.notices(sop, SPARE), [])
