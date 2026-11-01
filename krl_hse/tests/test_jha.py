import frappe
from frappe.model.workflow import WorkflowPermissionError
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, nowdate

from krl_hse.hse_health_safety_and_environment.doctype.hse_jha.hse_jha import (
	get_sop_details,
	hazards_from_hira,
	hira_lines,
)
from krl_hse.tests.utils import (
	act_on,
	current_fy,
	hira_line,
	jha_control,
	jha_hazard,
	make_approved_method_statement,
	make_approved_sop,
	make_area,
	make_branch,
	make_hira,
	make_jha,
	make_sop,
	make_user,
	make_work_order,
	override_setting,
	sop_content,
	sop_step,
)
from krl_hse.utils.controlled_document import get_approved_state, revision_status, start_revision

DOMAIN = "krl-test.example"
CREATOR = f"test.jha_officer_t@{DOMAIN}"
REVIEWER = f"test.jha_bhse_t@{DOMAIN}"
BRANCH_HEAD = f"test.jha_bhead_t@{DOMAIN}"
HO_TEAM = f"test.jha_ho@{DOMAIN}"
OTHER_BRANCH_USER = f"test.jha_officer_j@{DOMAIN}"

DOCTYPE = "HSE JHA"


class JHATestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_branch("TEST Athagarh", "T")
		make_branch("TEST Jharsuguda", "J")
		cls.order = make_work_order(
			"TEST Athagarh", "JHA-WO", work_title="TEST Slag handling", client_name="TEST Client Metals"
		)
		cls.area = make_area("TEST Athagarh", "TEST JHA Pit", work_order=cls.order.name)
		make_user(CREATOR, ["HSE Officer"], branches=["TEST Athagarh"])
		make_user(REVIEWER, ["Branch HSE Head"], branches=["TEST Athagarh"])
		make_user(BRANCH_HEAD, ["Branch Head"], branches=["TEST Athagarh"])
		make_user(HO_TEAM, ["HO HSE Team"])
		make_user(OTHER_BRANCH_USER, ["HSE Officer"], branches=["TEST Jharsuguda"])

	def setUp(self):
		self.ms = make_approved_method_statement("TEST Athagarh", self.order.name)
		self.sop = make_approved_sop(
			"TEST Athagarh",
			self.ms.name,
			area=self.area.name,
			steps=[
				sop_step(activity="TEST: isolate the cylinder valve"),
				sop_step(activity="TEST: light the torch"),
			],
		)

	def tearDown(self):
		frappe.set_user("Administrator")

	def new_jha(self, **kw):
		return make_jha("TEST Athagarh", self.sop.name, **kw)

	def problems(self, jha):
		return jha.review_problems()

	def state(self, jha):
		return frappe.db.get_value(DOCTYPE, jha.name, "workflow_state")

	def complete(self, **kw):
		"""A JHA with a hazard and a control measure for each of the two steps."""
		return self.new_jha(
			hazards=[jha_hazard("A1"), jha_hazard("A2", hazard="TEST: flashback")],
			controls=[jha_control("H1"), jha_control("H2", control="TEST: flashback arrestor")],
			**kw,
		)

	def go_to_ho(self, jha):
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		act_on(REVIEWER, DOCTYPE, jha.name, "Review and Forward")
		act_on(BRANCH_HEAD, DOCTYPE, jha.name, "Approve and Forward")

	def approve(self, jha):
		self.go_to_ho(jha)
		act_on(HO_TEAM, DOCTYPE, jha.name, "Approve")
		frappe.set_user("Administrator")
		return frappe.get_doc(DOCTYPE, jha.name)

	def approve_revision(self, jha):
		"""A revision skips the Branch HSE Head step."""
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		act_on(BRANCH_HEAD, DOCTYPE, jha.name, "Approve and Forward")
		act_on(HO_TEAM, DOCTYPE, jha.name, "Approve")
		frappe.set_user("Administrator")
		return frappe.get_doc(DOCTYPE, jha.name)


class TestNewJHA(JHATestCase):
	def test_number_and_starting_values(self):
		jha = self.new_jha()
		self.assertTrue(jha.name.startswith(f"KRL/JHA/T/{current_fy()}/"), jha.name)
		self.assertEqual(jha.document_number, jha.name)
		self.assertEqual(jha.revision_number, 0)
		self.assertEqual(jha.workflow_state, "Draft")
		self.assertEqual([s.action for s in jha.sign_offs], ["Prepared"])

	def test_the_header_comes_from_the_sop(self):
		jha = self.new_jha()
		self.assertEqual(jha.branch, "TEST Athagarh")
		self.assertEqual(jha.method_statement, self.ms.name)
		self.assertEqual(jha.work_order, self.order.name)
		self.assertEqual(jha.area, self.area.name)
		self.assertEqual(jha.sop_document_number, self.sop.document_number)
		self.assertEqual(jha.name_of_work, "TEST Slag handling")
		self.assertEqual(jha.client_name, "TEST Client Metals")

	def test_the_title_comes_from_the_sop_when_not_given(self):
		jha = make_jha("TEST Athagarh", self.sop.name, jha_title=None)
		self.assertEqual(jha.jha_title, self.sop.sop_title)

	def test_the_branch_can_be_left_out(self):
		jha = frappe.get_doc({"doctype": DOCTYPE, "sop": self.sop.name, **{"jha_title": "TEST x"}})
		jha.insert(ignore_permissions=True)
		self.assertEqual(jha.branch, "TEST Athagarh")

	def test_the_steps_start_as_the_steps_of_the_sop(self):
		jha = self.new_jha()
		self.assertEqual(
			[(r.step_ref, r.sop_step_ref, r.activity) for r in jha.steps],
			[
				("A1", "S1", "TEST: isolate the cylinder valve"),
				("A2", "S2", "TEST: light the torch"),
			],
		)

	def test_typed_steps_are_not_replaced_by_the_sop_steps(self):
		jha = self.new_jha(
			steps=[{"activity": "TEST: only this", "sop_step_ref": "S2"}], hazards=[], controls=[]
		)
		self.assertEqual([r.activity for r in jha.steps], ["TEST: only this"])

	def test_a_step_can_be_more_detailed_than_the_sop(self):
		jha = self.new_jha(
			steps=[
				{"activity": "TEST: close the valve", "sop_step_ref": "S1"},
				{"activity": "TEST: check the joints", "sop_step_ref": "S1"},
				{"activity": "TEST: an extra step with no SOP step"},
			],
			hazards=[],
			controls=[],
		)
		self.assertEqual([r.step_ref for r in jha.steps], ["A1", "A2", "A3"])
		self.assertFalse(jha.steps[2].sop_step_ref)

	def test_a_step_cannot_name_a_sop_step_that_does_not_exist(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(steps=[{"activity": "TEST: x", "sop_step_ref": "S9"}], hazards=[], controls=[])

	def test_the_ppe_starts_as_the_ppe_of_the_sop(self):
		jha = self.new_jha()
		self.assertTrue(self.sop.ppe)
		self.assertEqual(sorted(r.ppe for r in jha.ppe), sorted(r.ppe for r in self.sop.ppe))

	def test_typed_ppe_is_not_replaced(self):
		item = frappe.get_all("HSE PPE Item", pluck="name", limit=1)[0]
		jha = self.new_jha(ppe=[{"ppe": item}])
		self.assertEqual([r.ppe for r in jha.ppe], [item])

	def test_the_emergency_numbers_start_as_those_of_the_method_statement(self):
		contact = frappe.get_all("HSE Emergency Contact Type", pluck="name", limit=1)[0]
		frappe.get_doc("HSE Method Statement", self.ms.name)
		frappe.db.sql("delete from `tabHSE MS Emergency Number` where parent=%s", self.ms.name)
		frappe.get_doc(
			{
				"doctype": "HSE MS Emergency Number",
				"parent": self.ms.name,
				"parenttype": "HSE Method Statement",
				"parentfield": "emergency_numbers",
				"idx": 1,
				"contact_type": contact,
				"phone": "100",
				"details": "TEST: plant fire station",
			}
		).insert(ignore_permissions=True)
		jha = self.new_jha()
		self.assertEqual(
			[(r.contact_type, r.phone, r.details) for r in jha.emergency_contacts],
			[(contact, "100", "TEST: plant fire station")],
		)

	def test_hazards_and_controls_keep_their_references(self):
		jha = self.new_jha(
			hazards=[jha_hazard("A1"), jha_hazard("A1", hazard="TEST: second"), jha_hazard("A2")],
			controls=[jha_control("H1"), jha_control("H3")],
		)
		self.assertEqual([r.hazard_ref for r in jha.hazards], ["H1", "H2", "H3"])
		self.assertEqual([r.step_ref for r in jha.hazards], ["A1", "A1", "A2"])

	def test_a_reference_stays_with_its_hazard_when_another_is_removed(self):
		jha = self.new_jha(
			hazards=[jha_hazard("A1"), jha_hazard("A2"), jha_hazard("A2", hazard="TEST: third")],
			controls=[jha_control("H3")],
		)
		jha.hazards = [jha.hazards[0], jha.hazards[2]]
		jha.save()
		self.assertEqual([r.hazard_ref for r in jha.hazards], ["H1", "H3"])
		self.assertEqual(jha.controls[0].hazard_ref, "H3")

	def test_a_hazard_reference_cannot_be_used_twice(self):
		jha = self.new_jha()
		jha.hazards[0].hazard_ref = "H1"
		jha.append("hazards", jha_hazard("A2", hazard_ref="H1"))
		with self.assertRaises(frappe.ValidationError):
			jha.save()

	def test_a_hazard_must_belong_to_a_step_of_the_jha(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(hazards=[jha_hazard("A9")])

	def test_a_control_must_belong_to_a_hazard_of_the_jha(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(controls=[jha_control("H7")])

	def test_the_description_of_a_hazard_is_kept(self):
		jha = self.new_jha(
			hazards=[
				jha_hazard(
					source="Physical",
					cause="TEST: worn hose",
					environment="TEST: confined pit",
					trigger_condition="TEST: spark near the leak",
				)
			]
		)
		row = jha.hazards[0]
		self.assertEqual(
			(row.source, row.cause, row.environment, row.trigger_condition),
			("Physical", "TEST: worn hose", "TEST: confined pit", "TEST: spark near the leak"),
		)


class TestSOPRule(JHATestCase):
	def test_a_jha_cannot_be_made_without_a_sop(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": DOCTYPE, "branch": "TEST Athagarh", **{"jha_title": "x"}}).insert(
				ignore_permissions=True
			)

	def test_the_sop_must_be_approved(self):
		draft = make_sop("TEST Athagarh", self.ms.name)
		with self.assertRaises(frappe.ValidationError) as caught:
			make_jha("TEST Athagarh", draft.name)
		self.assertIn("approved SOP", str(caught.exception))

	def test_the_rule_can_accept_a_draft_sop(self):
		self.addCleanup(override_setting("parent_document_rule", "Any state"))
		draft = make_sop("TEST Athagarh", self.ms.name)
		self.assertEqual(make_jha("TEST Athagarh", draft.name).sop, draft.name)

	def test_an_expired_sop_cannot_be_chosen(self):
		frappe.db.set_value("HSE SOP", self.sop.name, "validity_date", add_days(nowdate(), -1))
		with self.assertRaises(frappe.ValidationError) as caught:
			self.new_jha()
		self.assertIn("expired", str(caught.exception))

	def test_a_superseded_sop_cannot_be_chosen_and_the_message_names_its_replacement(self):
		frappe.set_user(CREATOR)
		name = start_revision("HSE SOP", self.sop.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		revision = frappe.get_doc("HSE SOP", name)
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		frappe.db.set_value("HSE SOP", self.sop.name, "workflow_state", "Superseded")
		frappe.db.set_value("HSE SOP", name, "workflow_state", get_approved_state())
		with self.assertRaises(frappe.ValidationError) as caught:
			self.new_jha()
		self.assertIn(name, str(caught.exception))

	def test_the_sop_must_be_in_the_same_branch(self):
		with self.assertRaises(frappe.ValidationError):
			make_jha("TEST Jharsuguda", self.sop.name)

	def test_a_sop_has_one_jha(self):
		first = self.new_jha()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.new_jha()
		self.assertIn(first.name, str(caught.exception))

	def test_the_setting_can_allow_more_than_one(self):
		self.addCleanup(override_setting("jha_per_sop", "More than one allowed"))
		self.new_jha()
		self.assertTrue(self.new_jha().name)

	def test_a_different_sop_can_have_its_own_jha(self):
		self.new_jha()
		other = make_approved_sop("TEST Athagarh", self.ms.name, sop_title="TEST Other job")
		self.assertTrue(make_jha("TEST Athagarh", other.name).name)

	def test_the_area_must_belong_to_the_branch(self):
		other = make_area("TEST Jharsuguda", "TEST JHA Other Pit")
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(area=other.name)

	def test_reading_the_sop_for_the_form(self):
		frappe.set_user("Administrator")
		details = get_sop_details(self.sop.name)
		self.assertEqual(details["title"], self.sop.sop_title)
		self.assertEqual(details["notice"], "")
		self.assertEqual(
			[(s["sop_step_ref"], s["activity"]) for s in details["steps"]],
			[("S1", "TEST: isolate the cylinder valve"), ("S2", "TEST: light the torch")],
		)

	def test_the_form_is_told_when_the_sop_has_expired(self):
		frappe.db.set_value("HSE SOP", self.sop.name, "validity_date", add_days(nowdate(), -3))
		self.assertIn("expired", get_sop_details(self.sop.name)["notice"])

	def test_the_form_is_told_when_the_sop_is_not_in_force(self):
		frappe.db.set_value("HSE SOP", self.sop.name, "workflow_state", "Sent Back")
		self.assertIn("not in force", get_sop_details(self.sop.name)["notice"])


class TestHazardsFromHIRA(JHATestCase):
	def make_hira(self):
		return make_hira(
			"TEST Athagarh",
			self.ms.name,
			area=self.area.name,
			lines=[
				hira_line(
					hazard="TEST: loader near people",
					hazardous_event="TEST: loader hits a person",
					consequence_impact="TEST: serious injury",
					cause="TEST: poor visibility",
					existing_safeguard="TEST: banksman",
				),
				hira_line(hazard="TEST: hot slag"),
				hira_line(hazard="TEST: nothing recorded"),
			],
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Existing",
					"control": "TEST: barricade the lane",
					"hierarchy_level": "Isolation",
				},
				{
					"line_ref": "L2",
					"measure_type": "Existing",
					"control": "TEST: face shield",
					"hierarchy_level": "PPE",
				},
			],
		)

	def test_the_lines_of_a_hira_are_offered(self):
		hira = self.make_hira()
		self.assertEqual(
			[r["line_ref"] for r in hira_lines(hira.name)],
			["L1", "L2", "L3"],
		)

	def test_a_line_gives_a_hazard_with_its_controls(self):
		hira = self.make_hira()
		first = hazards_from_hira(hira.name, ["L1"])[0]
		self.assertEqual(first["hazard"]["hazard"], "TEST: loader near people")
		self.assertEqual(first["hazard"]["impact"], "TEST: serious injury")
		self.assertEqual(first["hazard"]["cause"], "TEST: poor visibility")
		self.assertEqual(first["hazard"]["trigger_condition"], "TEST: loader hits a person")
		self.assertEqual((first["hazard"]["hira"], first["hazard"]["hira_line"]), (hira.name, "L1"))
		self.assertEqual(
			first["controls"], [{"control": "TEST: barricade the lane", "hierarchy_level": "Isolation"}]
		)

	def test_only_the_chosen_lines_are_copied(self):
		hira = self.make_hira()
		self.assertEqual(len(hazards_from_hira(hira.name)), 3)
		self.assertEqual(
			[r["hazard"]["hira_line"] for r in hazards_from_hira(hira.name, '["L2", "L3"]')], ["L2", "L3"]
		)

	def test_a_line_with_only_a_safeguard_gets_it_as_an_untagged_control(self):
		hira = self.make_hira()
		frappe.db.sql("delete from `tabHSE HIRA Control` where parent=%s and line_ref='L1'", hira.name)
		first = hazards_from_hira(hira.name, ["L1"])[0]
		self.assertEqual(first["controls"], [{"control": "TEST: banksman", "hierarchy_level": None}])

	def test_a_line_with_nothing_gives_a_hazard_and_no_control(self):
		hira = self.make_hira()
		last = hazards_from_hira(hira.name, ["L3"])[0]
		self.assertEqual(last["controls"], [])

	def test_a_hazard_can_be_linked_to_a_hira_line(self):
		hira = self.make_hira()
		jha = self.new_jha(hazards=[jha_hazard(hira=hira.name, hira_line="L2")])
		self.assertEqual(jha.hazards[0].hira_line, "L2")

	def test_a_line_that_the_hira_does_not_have_is_refused(self):
		hira = self.make_hira()
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(hazards=[jha_hazard(hira=hira.name, hira_line="L9")])

	def test_a_line_without_a_hira_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(hazards=[jha_hazard(hira_line="L1")])

	def test_a_hira_of_another_method_statement_is_refused(self):
		other_ms = make_approved_method_statement("TEST Athagarh", self.order.name)
		hira = make_hira("TEST Athagarh", other_ms.name, area=self.area.name)
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(hazards=[jha_hazard(hira=hira.name, hira_line="L1")])

	def test_a_hira_of_another_branch_is_refused(self):
		order = make_work_order("TEST Jharsuguda", "JHA-WO2")
		area = make_area("TEST Jharsuguda", "TEST JHA J Pit", work_order=order.name)
		ms = make_approved_method_statement("TEST Jharsuguda", order.name)
		hira = make_hira("TEST Jharsuguda", ms.name, area=area.name)
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(hazards=[jha_hazard(hira=hira.name, hira_line="L1")])


class TestPeopleAndReferences(JHATestCase):
	def test_a_member_needs_a_name_or_an_employee(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(analysis_team=[{"role": "Operator"}])

	def test_the_consulted_employees_are_checked_too(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(employees_consulted=[{"role": "Operator"}])
		jha = self.new_jha(employees_consulted=[{"person_name": "TEST Fitter", "role": "Fitter"}])
		self.assertEqual(jha.employees_consulted[0].person_name, "TEST Fitter")

	def test_other_sops_can_be_listed_by_record_or_by_reference(self):
		other = make_approved_sop("TEST Athagarh", self.ms.name, sop_title="TEST Other job")
		jha = self.new_jha(
			reference_sops=[
				{"sop": other.name},
				{"reference": "KRL/OLD/SOP/07", "remarks": "TEST: paper SOP"},
			]
		)
		self.assertEqual(len(jha.reference_sops), 2)

	def test_a_reference_row_needs_a_sop_or_a_reference(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(reference_sops=[{"remarks": "TEST: nothing"}])

	def test_the_main_sop_is_not_listed_again(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(reference_sops=[{"sop": self.sop.name}])

	def test_a_reference_is_listed_once(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_jha(reference_sops=[{"reference": "KRL/OLD/SOP/07"}, {"reference": "KRL/OLD/SOP/07"}])


class TestReadyForReview(JHATestCase):
	def test_a_complete_jha_can_be_sent(self):
		jha = self.complete()
		self.assertEqual(self.problems(jha), [])
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		self.assertEqual(self.state(jha), "Pending Branch HSE Head Review")

	def test_a_draft_can_be_saved_incomplete_but_not_sent(self):
		jha = self.new_jha(hazards=[], controls=[], analysis_team=[])
		with self.assertRaises(frappe.ValidationError):
			act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		self.assertEqual(self.state(jha), "Draft")

	def test_a_step_without_a_hazard_is_named(self):
		jha = self.new_jha()
		self.assertTrue(any("A2" in p and "no hazard" in p for p in self.problems(jha)))

	def test_a_hazard_without_a_control_measure_is_named(self):
		jha = self.new_jha(controls=[])
		self.assertTrue(any("H1" in p and "at least one control measure" in p for p in self.problems(jha)))

	def test_a_control_measure_must_be_tagged_to_the_hierarchy_of_control(self):
		jha = self.new_jha(controls=[jha_control("H1", hierarchy_level=None)])
		self.assertTrue(any("hierarchy of control" in p for p in self.problems(jha)))

	def test_a_hazard_must_say_what_its_impact_is(self):
		jha = self.new_jha(hazards=[jha_hazard("A1", impact="")])
		self.assertTrue(any("impact" in p for p in self.problems(jha)))

	def test_the_team_must_be_named(self):
		jha = self.new_jha(analysis_team=[])
		self.assertTrue(any("hazard analysis team" in p for p in self.problems(jha)))

	def test_a_jha_without_steps_is_incomplete(self):
		jha = self.new_jha(steps=[], hazards=[], controls=[])
		# The steps of the SOP are filled when the JHA is made, so remove them to check the rule.
		jha.steps = []
		self.assertTrue(any("at least one step" in p for p in self.problems(jha)))

	def test_a_second_control_measure_for_a_hazard_is_fine(self):
		jha = self.complete()
		jha.append(
			"controls", jha_control("H1", control="TEST: fire extinguisher at hand", hierarchy_level="PPE")
		)
		jha.save()
		self.assertEqual(self.problems(jha), [])


class TestApprovalRoute(JHATestCase):
	def test_a_new_jha_goes_through_four_levels(self):
		jha = self.complete()
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		self.assertEqual(self.state(jha), "Pending Branch HSE Head Review")
		act_on(REVIEWER, DOCTYPE, jha.name, "Review and Forward")
		self.assertEqual(self.state(jha), "Pending Branch Head Approval")
		act_on(BRANCH_HEAD, DOCTYPE, jha.name, "Approve and Forward")
		self.assertEqual(self.state(jha), "Pending HO HSE Team Approval")
		act_on(HO_TEAM, DOCTYPE, jha.name, "Approve")
		self.assertEqual(self.state(jha), "Approved")
		frappe.set_user("Administrator")
		self.assertEqual(
			[s.action for s in frappe.get_doc(DOCTYPE, jha.name).sign_offs],
			["Prepared", "Submit for Review", "Review and Forward", "Approve and Forward", "Approve"],
		)

	def test_a_level_cannot_be_skipped_by_the_wrong_role(self):
		jha = self.complete()
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		with self.assertRaises((WorkflowPermissionError, frappe.ValidationError)):
			act_on(BRANCH_HEAD, DOCTYPE, jha.name, "Approve and Forward")

	def test_the_branch_head_cannot_give_the_final_approval(self):
		jha = self.complete()
		self.go_to_ho(jha)
		with self.assertRaises((WorkflowPermissionError, frappe.ValidationError)):
			act_on(BRANCH_HEAD, DOCTYPE, jha.name, "Approve")

	def test_sending_back_needs_recommendations_and_the_route_starts_again(self):
		jha = self.complete()
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		with self.assertRaises(frappe.ValidationError):
			act_on(REVIEWER, DOCTYPE, jha.name, "Send Back")
		act_on(REVIEWER, DOCTYPE, jha.name, "Send Back", recommendations="TEST: add the flashback hazard")
		self.assertEqual(self.state(jha), "Sent Back")
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		self.assertEqual(self.state(jha), "Pending Branch HSE Head Review")

	def test_approval_sets_the_issue_date(self):
		jha = self.approve(self.complete())
		self.assertEqual(str(jha.first_issue_date), nowdate())

	def test_an_approved_jha_cannot_be_edited_or_deleted(self):
		jha = self.approve(self.complete())
		jha.jha_title = "TEST changed"
		with self.assertRaises(frappe.ValidationError):
			jha.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(DOCTYPE, jha.name)

	def test_a_user_of_another_branch_cannot_see_it(self):
		jha = self.complete()
		frappe.set_user(OTHER_BRANCH_USER)
		self.assertFalse(frappe.has_permission(DOCTYPE, "read", doc=jha.name))


class TestRevision(JHATestCase):
	def setUp(self):
		super().setUp()
		self.jha = self.approve(self.complete())

	def revise(self):
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, self.jha.name, "Scheduled Review", "TEST: added a step")
		frappe.set_user("Administrator")
		return frappe.get_doc(DOCTYPE, name)

	def test_a_revision_keeps_the_content_and_references(self):
		revision = self.revise()
		self.assertEqual(revision.name, f"{self.jha.document_number}-R1")
		self.assertEqual(revision.revision_number, 1)
		self.assertEqual([r.step_ref for r in revision.steps], ["A1", "A2"])
		self.assertEqual([r.hazard_ref for r in revision.hazards], ["H1", "H2"])
		self.assertEqual([r.hazard_ref for r in revision.controls], ["H1", "H2"])
		self.assertEqual(revision.sop, self.sop.name)
		self.assertEqual(revision.sop_document_number, self.sop.document_number)

	def test_a_revision_is_not_blocked_by_the_one_jha_per_sop_rule(self):
		self.assertEqual(self.revise().previous_revision, self.jha.name)

	def test_a_revision_goes_straight_to_the_branch_head(self):
		revision = self.revise()
		act_on(CREATOR, DOCTYPE, revision.name, "Submit for Review")
		self.assertEqual(self.state(revision), "Pending Branch Head Approval")

	def test_the_revision_has_three_levels(self):
		revision = self.approve_revision(self.revise())
		self.assertEqual(revision.workflow_state, "Approved")
		self.assertEqual(frappe.db.get_value(DOCTYPE, self.jha.name, "workflow_state"), "Superseded")

	def test_the_earlier_revision_stays_in_force_until_the_new_one_is_approved(self):
		self.revise()
		self.assertEqual(frappe.db.get_value(DOCTYPE, self.jha.name, "workflow_state"), "Approved")

	def test_a_revision_can_move_to_a_later_revision_of_the_same_sop(self):
		frappe.set_user(CREATOR)
		new_sop = start_revision("HSE SOP", self.sop.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		revised = frappe.get_doc("HSE SOP", new_sop)
		revised.validity_date = add_months(nowdate(), 12)
		revised.save(ignore_permissions=True)
		frappe.db.set_value("HSE SOP", self.sop.name, "workflow_state", "Superseded")
		frappe.db.set_value("HSE SOP", new_sop, "workflow_state", get_approved_state())

		revision = self.revise()
		revision.sop = new_sop
		revision.save()
		self.assertEqual(revision.sop, new_sop)
		self.assertEqual(revision.sop_document_number, self.sop.document_number)

	def test_a_revision_cannot_move_to_a_different_sop(self):
		other = make_approved_sop("TEST Athagarh", self.ms.name, sop_title="TEST Other job")
		revision = self.revise()
		revision.sop = other.name
		with self.assertRaises(frappe.ValidationError):
			revision.save()

	def test_a_revision_of_a_jha_whose_sop_has_expired_can_still_be_started(self):
		frappe.db.set_value("HSE SOP", self.sop.name, "validity_date", add_days(nowdate(), -5))
		self.assertTrue(self.revise().name)

	def test_the_form_is_told_when_the_sop_has_been_replaced(self):
		frappe.set_user(CREATOR)
		new_sop = start_revision("HSE SOP", self.sop.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		frappe.db.set_value("HSE SOP", self.sop.name, "workflow_state", "Superseded")
		frappe.db.set_value("HSE SOP", new_sop, "workflow_state", get_approved_state())
		self.assertIn(new_sop, get_sop_details(self.sop.name)["notice"])

	def test_the_revision_status_carries_the_notice_about_the_sop(self):
		self.assertEqual(revision_status(DOCTYPE, self.jha.name)["notice"], "")
		frappe.db.set_value("HSE SOP", self.sop.name, "validity_date", add_days(nowdate(), -2))
		self.assertIn("expired", revision_status(DOCTYPE, self.jha.name)["notice"])

	def test_a_superseded_jha_carries_no_notice(self):
		self.approve_revision(self.revise())
		frappe.db.set_value("HSE SOP", self.sop.name, "validity_date", add_days(nowdate(), -2))
		self.assertEqual(revision_status(DOCTYPE, self.jha.name)["notice"], "")

	def test_other_document_types_carry_no_notice(self):
		self.assertEqual(revision_status("HSE SOP", self.sop.name)["notice"], "")
		self.assertEqual(revision_status("HSE Method Statement", self.ms.name)["notice"], "")
