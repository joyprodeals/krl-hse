import frappe
from frappe.model.workflow import WorkflowPermissionError, WorkflowTransitionError
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from krl_hse.tests.utils import (
	act_on,
	current_fy,
	make_area,
	make_branch,
	make_method_statement,
	make_user,
	make_work_order,
	method_statement_content,
)
from krl_hse.utils.controlled_document import revision_status, start_revision

DOMAIN = "krl-test.example"
CREATOR = f"test.ms_officer_t@{DOMAIN}"
REVIEWER = f"test.ms_branch_head_t@{DOMAIN}"
APPROVER = f"test.ms_hse_head@{DOMAIN}"
VIEWER = f"test.ms_viewer_t@{DOMAIN}"
OTHER_BRANCH = f"test.ms_branch_head_j@{DOMAIN}"


class MethodStatementTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_branch("TEST Athagarh", "T")
		make_branch("TEST Jharsuguda", "J")
		cls.order = make_work_order(
			"TEST Athagarh",
			"MS-WO",
			work_title="TEST Material handling",
			client_name="TEST Client Metals",
			plant_name="TEST Plant",
			plant_address="Athagarh",
			start_date="2026-04-01",
			completion_date="2027-03-31",
			contacts=[
				{"contact_role": "Branch Head", "contact_name": "TEST Branch Head"},
				{"contact_role": "Client Representative", "contact_name": "TEST Client Rep"},
			],
			service_lines=[{"service_code": "S1", "description": "TEST Loading", "qty": 1}],
		)
		make_user(CREATOR, ["HSE Officer"], branches=["TEST Athagarh"])
		make_user(REVIEWER, ["Branch Head"], branches=["TEST Athagarh"])
		make_user(APPROVER, ["HSE Head"])
		make_user(VIEWER, ["Site Supervisor"], branches=["TEST Athagarh"])
		make_user(OTHER_BRANCH, ["Branch Head"], branches=["TEST Jharsuguda"])

	def tearDown(self):
		frappe.set_user("Administrator")

	def new_ms(self, **kw):
		values = method_statement_content()
		values.update(kw)
		return make_method_statement("TEST Athagarh", self.order.name, **values)

	def approve(self, ms):
		act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review")
		act_on(REVIEWER, "HSE Method Statement", ms.name, "Review and Forward")
		act_on(APPROVER, "HSE Method Statement", ms.name, "Approve")
		frappe.set_user("Administrator")
		return frappe.get_doc("HSE Method Statement", ms.name)


class TestNewMethodStatement(MethodStatementTestCase):
	def test_number_and_starting_values(self):
		ms = self.new_ms()
		self.assertTrue(ms.name.startswith(f"KRL/MS/T/{current_fy()}/"), ms.name)
		self.assertEqual(ms.document_number, ms.name)
		self.assertEqual(ms.revision_number, 0)
		self.assertEqual(ms.workflow_state, "Draft")
		self.assertEqual([s.action for s in ms.sign_offs], ["Prepared"])

	def test_numbers_are_not_reused(self):
		first, second = self.new_ms(), self.new_ms()
		self.assertNotEqual(first.name, second.name)

	def test_project_details_come_from_the_work_order(self):
		ms = self.new_ms()
		self.assertEqual(ms.name_of_work, "TEST Material handling")
		self.assertEqual(ms.client_name, "TEST Client Metals")
		self.assertEqual(ms.location, "TEST Plant, Athagarh")
		self.assertEqual(str(ms.work_start_date), "2026-04-01")
		self.assertEqual(
			sorted(row.contact_name for row in ms.management), ["TEST Branch Head", "TEST Client Rep"]
		)

	def test_typed_values_are_not_overwritten(self):
		ms = self.new_ms(name_of_work="TEST Typed name")
		self.assertEqual(ms.name_of_work, "TEST Typed name")

	def test_basic_ppe_and_emergency_numbers_start_filled(self):
		ms = self.new_ms()
		self.assertEqual(len(ms.ppe), frappe.db.count("HSE PPE Item", {"is_basic": 1}))
		self.assertTrue(all(row.activity == "Basic" for row in ms.ppe))
		self.assertEqual(len(ms.emergency_numbers), frappe.db.count("HSE Emergency Contact Type"))

	def test_work_must_be_in_the_same_branch(self):
		with self.assertRaises(frappe.ValidationError):
			make_method_statement("TEST Jharsuguda", self.order.name, **method_statement_content())

	def test_no_new_document_for_a_cancelled_work(self):
		order = make_work_order("TEST Athagarh", "MS-WO-OLD", status="Cancelled")
		with self.assertRaises(frappe.ValidationError):
			make_method_statement("TEST Athagarh", order.name, **method_statement_content())

	def test_one_work_can_have_many_method_statements(self):
		for _i in range(3):
			self.new_ms()
		self.assertGreaterEqual(frappe.db.count("HSE Method Statement", {"work_order": self.order.name}), 3)

	def test_end_date_cannot_be_before_start(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_ms(work_start_date="2026-05-01", work_end_date="2026-04-01")


class TestWorkReferences(MethodStatementTestCase):
	def test_a_row_must_name_a_listed_work(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_ms(equipment=[{"work": "TEST Not a work", "equipment": "TEST Loader", "qty": 1}])

	def test_common_work_names_are_allowed(self):
		ms = self.new_ms(
			equipment=[{"work": "General", "equipment": "TEST Bus", "qty": 1}],
			manpower=[{"work": "Administration", "designation": self.designation(), "qty": 2}],
		)
		self.assertEqual(ms.equipment[0].work, "General")

	def test_a_work_listed_twice_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_ms(works=[{"work_name": "TEST Pit"}, {"work_name": "test pit"}])

	def test_removing_a_work_that_is_still_used_is_refused(self):
		ms = self.new_ms()
		ms.works = []
		with self.assertRaises(frappe.ValidationError):
			ms.save()

	def designation(self):
		if not frappe.db.exists("Designation", "TEST Operator"):
			frappe.get_doc({"doctype": "Designation", "designation_name": "TEST Operator"}).insert()
		return "TEST Operator"


class TestAreas(MethodStatementTestCase):
	def area(self, branch="TEST Athagarh", name="TEST MS Yard", **kw):
		return make_area(
			branch,
			name,
			team=[
				{
					"team_role": "Team Lead",
					"member_name": "TEST Yard Lead",
					"category": "SL",
					"from_date": "2026-04-01",
				}
			],
			location_details="TEST: gate 1",
			**kw,
		)

	def test_the_leader_and_details_come_from_the_area(self):
		area = self.area()
		ms = self.new_ms(areas=[{"area": area.name}])
		self.assertEqual(ms.areas[0].leader_name, "TEST Yard Lead")
		self.assertEqual(ms.areas[0].leader_category, "SL")
		self.assertEqual(ms.areas[0].details, "TEST: gate 1")

	def test_an_area_of_another_branch_is_refused(self):
		area = self.area(branch="TEST Jharsuguda", name="TEST MS Pit")
		with self.assertRaises(frappe.ValidationError):
			self.new_ms(areas=[{"area": area.name}])

	def test_an_area_of_another_work_is_refused(self):
		other = make_work_order("TEST Athagarh", "MS-WO-2")
		area = self.area(name="TEST MS Other Work", work_order=other.name)
		with self.assertRaises(frappe.ValidationError):
			self.new_ms(areas=[{"area": area.name}])

	def test_an_area_of_this_work_is_accepted(self):
		area = self.area(name="TEST MS Own Work", work_order=self.order.name)
		self.assertEqual(self.new_ms(areas=[{"area": area.name}]).areas[0].area, area.name)

	def test_a_disabled_area_is_refused(self):
		area = self.area(name="TEST MS Disabled", disabled=1)
		with self.assertRaises(frappe.ValidationError):
			self.new_ms(areas=[{"area": area.name}])


class TestApproval(MethodStatementTestCase):
	def test_it_cannot_be_sent_for_review_without_works_and_steps(self):
		ms = make_method_statement("TEST Athagarh", self.order.name)
		with self.assertRaises(frappe.ValidationError):
			act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review")

	def test_a_work_without_steps_is_refused_at_review(self):
		ms = self.new_ms(
			works=[{"work_name": "TEST Pit"}, {"work_name": "TEST Yard"}],
			operations=[{"work": "TEST Pit", "operation": "TEST: step"}],
		)
		with self.assertRaises(frappe.ValidationError):
			act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review")

	def test_three_levels_to_approved(self):
		ms = self.new_ms()
		self.assertEqual(
			act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review").workflow_state,
			"Pending Branch Head Review",
		)
		self.assertEqual(
			act_on(REVIEWER, "HSE Method Statement", ms.name, "Review and Forward").workflow_state,
			"Pending HSE Head Approval",
		)
		self.assertEqual(
			act_on(APPROVER, "HSE Method Statement", ms.name, "Approve").workflow_state, "Approved"
		)

	def test_approval_stamps_the_issue_date_and_the_sign_offs(self):
		ms = self.approve(self.new_ms())
		self.assertEqual(str(ms.first_issue_date), nowdate())
		self.assertFalse(ms.revision_date)
		self.assertEqual(
			[s.action for s in ms.sign_offs],
			["Prepared", "Submit for Review", "Review and Forward", "Approve"],
		)
		self.assertEqual([s.user for s in ms.sign_offs][-1], APPROVER)

	def test_the_branch_head_cannot_give_the_final_approval(self):
		ms = self.new_ms()
		act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review")
		act_on(REVIEWER, "HSE Method Statement", ms.name, "Review and Forward")
		with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError)):
			act_on(REVIEWER, "HSE Method Statement", ms.name, "Approve")

	def test_the_creator_cannot_review(self):
		ms = self.new_ms()
		act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review")
		with self.assertRaises((WorkflowPermissionError, WorkflowTransitionError)):
			act_on(CREATOR, "HSE Method Statement", ms.name, "Review and Forward")

	def test_sent_back_needs_recommendations_and_can_be_resubmitted(self):
		ms = self.new_ms()
		act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review")
		with self.assertRaises(frappe.ValidationError):
			act_on(REVIEWER, "HSE Method Statement", ms.name, "Send Back")
		sent = act_on(
			REVIEWER, "HSE Method Statement", ms.name, "Send Back", recommendations="TEST: add gas cutting"
		)
		self.assertEqual(sent.workflow_state, "Sent Back")
		self.assertEqual(sent.sign_offs[-1].remarks, "TEST: add gas cutting")
		self.assertEqual(
			act_on(CREATOR, "HSE Method Statement", ms.name, "Submit for Review").workflow_state,
			"Pending Branch Head Review",
		)

	def test_a_branch_head_of_another_branch_cannot_see_it(self):
		ms = self.new_ms()
		frappe.set_user(OTHER_BRANCH)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("HSE Method Statement", ms.name).check_permission("read")


class TestFrozenWhenApproved(MethodStatementTestCase):
	def test_an_approved_document_cannot_be_changed(self):
		ms = self.approve(self.new_ms())
		ms.name_of_work = "TEST Changed"
		with self.assertRaises(frappe.ValidationError):
			ms.save(ignore_permissions=True)

	def test_an_approved_document_cannot_be_deleted(self):
		ms = self.approve(self.new_ms())
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("HSE Method Statement", ms.name, force=True)

	def test_a_draft_can_be_changed_and_deleted(self):
		ms = self.new_ms()
		ms.name_of_work = "TEST Edited draft"
		ms.save()
		frappe.delete_doc("HSE Method Statement", ms.name, force=True)
		self.assertFalse(frappe.db.exists("HSE Method Statement", ms.name))

	def test_the_approved_state_name_is_a_setting(self):
		settings = frappe.get_doc("HSE Settings")
		settings.approved_state = "Released"
		settings.save(ignore_permissions=True)
		frappe.clear_cache(doctype="HSE Settings")
		try:
			ms = self.new_ms()
			ms.db_set("workflow_state", "Released")
			ms.reload()
			ms.name_of_work = "TEST Edited"
			with self.assertRaises(frappe.ValidationError):
				ms.save(ignore_permissions=True)
		finally:
			settings.approved_state = "Approved"
			settings.save(ignore_permissions=True)
			frappe.clear_cache(doctype="HSE Settings")


class TestRevisions(MethodStatementTestCase):
	def revise(self, ms, user=CREATOR, **kw):
		frappe.set_user(user)
		values = {"revision_trigger": "Client Requirement", "revision_remark": "TEST: client added a gate"}
		values.update(kw)
		name = start_revision("HSE Method Statement", ms.name, **values)
		frappe.set_user("Administrator")
		return frappe.get_doc("HSE Method Statement", name)

	def test_a_revision_keeps_the_number_and_adds_the_revision(self):
		ms = self.approve(self.new_ms())
		rev = self.revise(ms)
		self.assertEqual(rev.name, f"{ms.name}-R1")
		self.assertEqual(rev.document_number, ms.document_number)
		self.assertEqual(rev.revision_number, 1)
		self.assertEqual(rev.previous_revision, ms.name)
		self.assertEqual(rev.workflow_state, "Draft")
		self.assertEqual(str(rev.first_issue_date), str(ms.first_issue_date))
		self.assertEqual(len(rev.works), len(ms.works))
		self.assertEqual([s.action for s in rev.sign_offs], ["Prepared"])

	def test_the_approved_revision_stays_in_force_until_the_new_one_is_approved(self):
		ms = self.approve(self.new_ms())
		rev = self.revise(ms)
		self.assertEqual(frappe.db.get_value("HSE Method Statement", ms.name, "workflow_state"), "Approved")

		rev = self.approve(rev)
		self.assertEqual(frappe.db.get_value("HSE Method Statement", ms.name, "workflow_state"), "Superseded")
		self.assertEqual(rev.workflow_state, "Approved")
		self.assertEqual(str(rev.revision_date), nowdate())

	def test_a_superseded_document_cannot_be_changed_or_revised(self):
		ms = self.approve(self.new_ms())
		self.approve(self.revise(ms))
		ms.reload()
		ms.name_of_work = "TEST Changed"
		with self.assertRaises(frappe.ValidationError):
			ms.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.revise(ms)

	def test_only_an_approved_document_can_be_revised(self):
		with self.assertRaises(frappe.ValidationError):
			self.revise(self.new_ms())

	def test_there_cannot_be_two_open_revisions(self):
		ms = self.approve(self.new_ms())
		self.revise(ms)
		with self.assertRaises(frappe.ValidationError):
			self.revise(ms)

	def test_a_revision_says_what_triggered_it(self):
		ms = self.approve(self.new_ms())
		with self.assertRaises(frappe.ValidationError):
			self.revise(ms, revision_remark="")

	def test_a_revision_of_a_revision_continues_the_number(self):
		ms = self.approve(self.new_ms())
		first = self.approve(self.revise(ms))
		second = self.revise(first)
		self.assertEqual(second.name, f"{ms.name}-R2")
		self.assertEqual(second.revision_number, 2)

	def test_a_viewer_cannot_start_a_revision(self):
		ms = self.approve(self.new_ms())
		with self.assertRaises(frappe.PermissionError):
			self.revise(ms, user=VIEWER)

	def test_the_form_is_told_whether_the_user_can_revise(self):
		ms = self.approve(self.new_ms())
		frappe.set_user(CREATOR)
		status = revision_status("HSE Method Statement", ms.name)
		self.assertTrue(status["can_revise"])
		self.assertTrue(status["is_latest"])
		frappe.set_user(VIEWER)
		self.assertFalse(revision_status("HSE Method Statement", ms.name)["can_revise"])

	def test_the_old_revision_points_to_the_latest(self):
		ms = self.approve(self.new_ms())
		rev = self.revise(ms)
		frappe.set_user(CREATOR)
		status = revision_status("HSE Method Statement", ms.name)
		self.assertFalse(status["is_latest"])
		self.assertEqual(status["latest"], rev.name)
		self.assertFalse(status["can_revise"])


class TestWhoSeesWhat(MethodStatementTestCase):
	def test_a_viewer_sees_approved_documents_only(self):
		draft = self.new_ms()
		approved = self.approve(self.new_ms())

		frappe.set_user(VIEWER)
		names = frappe.get_list("HSE Method Statement", pluck="name")
		self.assertIn(approved.name, names)
		self.assertNotIn(draft.name, names)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("HSE Method Statement", draft.name).check_permission("read")

	def test_the_preparer_and_approvers_see_drafts(self):
		draft = self.new_ms()
		for user in (CREATOR, REVIEWER, APPROVER):
			frappe.set_user(user)
			self.assertIn(draft.name, frappe.get_list("HSE Method Statement", pluck="name"), user)

	def test_a_viewer_does_not_see_a_draft_revision(self):
		ms = self.approve(self.new_ms())
		frappe.set_user(CREATOR)
		rev = start_revision("HSE Method Statement", ms.name, "Client Requirement", "TEST: change")
		frappe.set_user(VIEWER)
		names = frappe.get_list("HSE Method Statement", pluck="name")
		self.assertIn(ms.name, names)
		self.assertNotIn(rev, names)
		status = revision_status("HSE Method Statement", ms.name)
		self.assertTrue(status["is_latest"])

	def test_who_sees_drafts_follows_the_workflow(self):
		"""Removing a role from the workflow takes the drafts away from it, with no code change."""
		draft = self.new_ms()
		frappe.set_user(VIEWER)
		self.assertNotIn(draft.name, frappe.get_list("HSE Method Statement", pluck="name"))

		frappe.set_user("Administrator")
		workflow = frappe.get_doc("Workflow", "HSE Method Statement Approval")
		workflow.append("states", {"state": "Draft", "doc_status": "0", "allow_edit": "Site Supervisor"})
		workflow.save()
		frappe.clear_cache()
		try:
			frappe.set_user(VIEWER)
			self.assertIn(draft.name, frappe.get_list("HSE Method Statement", pluck="name"))
		finally:
			frappe.set_user("Administrator")
			workflow.reload()
			workflow.states = [r for r in workflow.states if r.allow_edit != "Site Supervisor"]
			workflow.save()
			frappe.clear_cache()


class TestGuards(IntegrationTestCase):
	def test_every_controlled_doctype_is_a_branch_doctype_with_the_control_fields(self):
		controlled = frappe.get_hooks("hse_controlled_doctypes")
		self.assertIn("HSE Method Statement", controlled)
		for doctype in controlled:
			self.assertIn(doctype, frappe.get_hooks("hse_branch_doctypes"))
			meta = frappe.get_meta(doctype)
			for fieldname in (
				"document_number",
				"revision_number",
				"previous_revision",
				"first_issue_date",
				"revision_date",
				"workflow_state",
				"sign_offs",
				"recommendations",
				"work_order",
			):
				self.assertTrue(meta.has_field(fieldname), f"{doctype} has no {fieldname}")
			self.assertTrue(meta.get_workflow(), f"{doctype} has no workflow")

	def test_the_boot_info_lists_controlled_doctypes(self):
		from krl_hse.utils.boot import boot_session

		bootinfo = frappe._dict()
		boot_session(bootinfo)
		self.assertIn("HSE Method Statement", bootinfo.hse_controlled_doctypes)

	def test_masters_start_filled(self):
		self.assertEqual(frappe.db.count("HSE Emergency Contact Type"), 5)
		self.assertTrue(frappe.db.exists("HSE Common Work", "General"))
		self.assertTrue(frappe.db.exists("HSE PPE Item", "Helmet"))
