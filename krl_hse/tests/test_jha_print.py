import frappe

from krl_hse.tests.test_jha import (
	BRANCH_HEAD,
	CREATOR,
	DOCTYPE,
	HO_TEAM,
	REVIEWER,
	JHATestCase,
)
from krl_hse.tests.utils import (
	act_on,
	hira_line,
	jha_control,
	jha_hazard,
	make_approved_sop,
	make_hira,
	override_setting,
)
from krl_hse.utils.controlled_document import start_revision
from krl_hse.utils.printing import hse_format_identity, hse_signatures


class TestJHAPrint(JHATestCase):
	def printed(self, jha):
		frappe.set_user("Administrator")
		return frappe.get_print(DOCTYPE, jha.name, DOCTYPE)

	def full_jha(self, **kw):
		contact = frappe.get_all("HSE Emergency Contact Type", pluck="name", limit=1)[0]
		values = {
			"employees_consulted": [{"person_name": "TEST Loader operator", "role": "Operator"}],
			"resources": [
				{"resource": "TEST: gas cutting set", "qty": 2},
				{"resource": "TEST: fire blanket", "remarks": "TEST: near the pit"},
			],
			"emergency_contacts": [{"contact_type": contact, "phone": "TEST-100", "details": "TEST: gate 2"}],
			"training": [{"topic": "TEST: hot work safety", "for_whom": "TEST gas cutters"}],
			"hazards": [
				jha_hazard(
					"A1",
					hazard="TEST: gas leak",
					source="TEST: cylinder",
					cause="TEST: loose joint",
					environment="TEST: closed pit",
					trigger_condition="TEST: valve opened",
				),
				jha_hazard("A1", hazard="TEST: sparks", impact="TEST: burns"),
				jha_hazard("A2", hazard="TEST: flashback", impact="TEST: fire"),
			],
			"controls": [
				jha_control("H1", control="TEST: soap test on the joints"),
				jha_control("H1", control="TEST: fire extinguisher at hand", hierarchy_level="PPE"),
				jha_control("H2", control="TEST: screens around the cut"),
				jha_control("H3", control="TEST: flashback arrestor"),
			],
		}
		values.update(kw)
		return self.new_jha(**values)

	# --- Identity ------------------------------------------------------------------------------

	def test_print_carries_the_format_identity_and_dates(self):
		jha = self.approve(self.full_jha())
		html = self.printed(jha)
		identity = hse_format_identity(DOCTYPE)
		self.assertEqual(identity["format_number"], "KRL/HSE/JHA/1")
		self.assertEqual(identity["format_revision"], "01/24")
		for text in (
			"KRL/HSE/JHA/1",
			"01/24",
			identity["internal_line"],
			jha.document_number,
			self.sop.document_number,
			self.ms.name,
		):
			self.assertIn(text, html)
		self.assertIn(frappe.utils.formatdate(jha.first_issue_date), html)

	def test_a_jha_has_no_valid_until_date(self):
		self.assertNotIn("Valid Until", self.printed(self.full_jha()))

	def test_only_an_unapproved_print_says_so(self):
		jha = self.full_jha()
		self.assertIn("NOT APPROVED", self.printed(jha))
		self.assertNotIn("NOT APPROVED", self.printed(self.approve(jha)))

	def test_a_superseded_print_says_a_later_revision_is_in_force(self):
		jha = self.approve(self.full_jha())
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, jha.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		self.approve_revision(frappe.get_doc(DOCTYPE, name))
		self.assertIn("SUPERSEDED", self.printed(jha))

	# --- Content -------------------------------------------------------------------------------

	def test_every_part_of_the_format_is_printed(self):
		html = self.printed(self.full_jha())
		for text in (
			"Job Hazard Analysis",
			"TEST Gas cutting JHA",
			"Project Details",
			"TEST Athagarh",
			"Reference SOPs",
			"Hazard Analysis Team",
			"TEST Gas cutter",
			"Employees Consulted",
			"TEST Loader operator",
			"Equipment and Resources",
			"TEST: gas cutting set",
			"Emergency Contacts",
			"TEST-100",
			"TEST: gate 2",
			"Training to be Imparted",
			"TEST: hot work safety",
			"TEST gas cutters",
			"Mandatory PPE Recommended",
			"Sequence of Job Steps (Activity)",
			"Potential Hazard",
			"Impact",
			"Safeguard and Control Measures",
		):
			self.assertIn(text, html)

	def test_the_six_rows_of_the_form_are_printed_even_when_empty(self):
		html = self.printed(self.new_jha(analysis_team=[], emergency_contacts=[], resources=[], training=[]))
		for text in (
			"Reference SOPs",
			"Hazard Analysis Team",
			"Equipment and Resources",
			"Emergency Contacts",
			"Training to be Imparted",
		):
			self.assertIn(text, html)

	def test_employees_consulted_is_printed_only_when_there_are_some(self):
		self.addCleanup(override_setting("jha_per_sop", "More than one allowed"))
		self.assertIn("Employees Consulted", self.printed(self.full_jha()))
		self.assertNotIn("Employees Consulted", self.printed(self.new_jha()))

	def test_the_quantity_of_a_resource_is_printed_as_a_whole_number(self):
		html = self.printed(self.full_jha())
		self.assertIn("Qty: 2)", html)
		self.assertNotIn("Qty: 2.0", html)

	def test_the_sop_of_the_jha_is_listed_first_then_the_other_sops(self):
		other = make_approved_sop("TEST Athagarh", self.ms.name, sop_title="TEST Other SOP the job follows")
		html = self.printed(
			self.full_jha(reference_sops=[{"sop": other.name}, {"reference": "TEST: old paper SOP 12"}])
		)
		listed = html.split("Reference SOPs")[1].split("Hazard Analysis Team")[0]
		self.assertLess(listed.index(self.sop.document_number), listed.index(other.document_number))
		self.assertLess(listed.index(other.document_number), listed.index("TEST: old paper SOP 12"))
		self.assertIn("TEST Other SOP the job follows", listed)

	def test_the_steps_are_printed_in_order_with_their_references(self):
		html = self.printed(self.full_jha())
		self.assertLess(html.index("TEST: isolate the cylinder valve"), html.index("TEST: light the torch"))
		self.assertIn(">A1<", html)
		self.assertIn(">A2<", html)
		self.assertIn("SOP step S1", html)

	def test_a_step_with_two_hazards_has_a_row_for_each_and_the_step_spans_them(self):
		html = self.printed(self.full_jha())
		table = html.split("Sequence of Job Steps (Activity)")[1]
		self.assertEqual(table.count("TEST: isolate the cylinder valve"), 1)
		self.assertEqual(table.count('rowspan="2"'), 2)
		self.assertEqual(table.count('rowspan="1"'), 2)

	def test_each_hazard_has_its_own_impact_and_control_measures(self):
		table = self.printed(self.full_jha()).split("Sequence of Job Steps (Activity)")[1]
		for text in (
			"TEST: gas leak",
			"TEST: soap test on the joints",
			"TEST: fire extinguisher at hand",
			"TEST: sparks",
			"TEST: burns",
			"TEST: screens around the cut",
			"TEST: flashback",
			"TEST: flashback arrestor",
		):
			self.assertIn(text, table)
		# A hazard's controls come right after the hazard, not after another one.
		self.assertLess(table.index("TEST: soap test on the joints"), table.index("TEST: sparks"))
		self.assertLess(table.index("TEST: screens around the cut"), table.index("TEST: flashback"))

	def test_control_measures_are_numbered_and_show_their_level_of_control(self):
		table = self.printed(self.full_jha()).split("Sequence of Job Steps (Activity)")[1]
		self.assertEqual(table.count("<ol>"), 3)
		self.assertIn("TEST: soap test on the joints <span", table)
		self.assertIn("(Isolation)", table)
		self.assertIn("(PPE)", table)

	def test_the_details_of_a_hazard_are_printed_under_it(self):
		table = self.printed(self.full_jha()).split("Sequence of Job Steps (Activity)")[1]
		for text in (
			"Source: TEST: cylinder",
			"Environment: TEST: closed pit",
			"Cause: TEST: loose joint",
			"Triggered when: TEST: valve opened",
		):
			self.assertIn(text, table)

	def test_a_hazard_that_came_from_a_hira_names_its_line(self):
		hira = make_hira(
			"TEST Athagarh",
			self.ms.name,
			area=self.area.name,
			lines=[hira_line(hazard="TEST: loader near people")],
		)
		jha = self.full_jha(
			hazards=[
				jha_hazard("A1", hira=hira.name, hira_line="L1"),
				jha_hazard("A2", hazard="TEST: flashback"),
			],
			controls=[jha_control("H1"), jha_control("H2")],
		)
		html = self.printed(jha)
		self.assertIn(f"HIRA: {hira.name}, line L1", html)
		self.assertEqual(html.count("HIRA: "), 1)

	def test_a_step_with_no_hazard_yet_is_still_printed(self):
		jha = self.new_jha()
		html = self.printed(jha)
		self.assertIn("TEST: light the torch", html)
		self.assertIn("TEST: isolate the cylinder valve", html)

	def test_typed_text_is_escaped(self):
		jha = self.full_jha()
		frappe.db.set_value(
			"HSE JHA Hazard", jha.hazards[0].name, "hazard", "TEST <script>alert(1)</script> gas"
		)
		html = self.printed(jha)
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

	# --- PPE pictures --------------------------------------------------------------------------

	def test_ppe_is_listed_with_the_picture_from_the_master(self):
		items = frappe.get_all("HSE PPE Item", pluck="name", limit=2)
		frappe.db.set_value("HSE PPE Item", items[0], "image", "/files/test-ppe-picture.png")
		jha = self.full_jha(ppe=[{"ppe": items[0]}, {"ppe": items[1], "remarks": "TEST: with side shields"}])
		html = self.printed(jha)
		self.assertIn('src="/files/test-ppe-picture.png"', html)
		self.assertIn("TEST: with side shields", html)

	def test_a_jha_without_ppe_has_no_empty_ppe_table(self):
		jha = self.full_jha(ppe=[])
		frappe.db.delete("HSE JHA PPE", {"parent": jha.name})
		self.assertNotIn("Mandatory PPE Recommended", self.printed(frappe.get_doc(DOCTYPE, jha.name)))

	# --- Client details ------------------------------------------------------------------------

	def test_client_format_is_printed_only_when_it_applies(self):
		self.addCleanup(override_setting("jha_per_sop", "More than one allowed"))
		self.assertNotIn("Client Document Details", self.printed(self.full_jha()))
		html = self.printed(
			self.full_jha(client_format_applies=1, client_document_number="TEST-CLIENT-DOC-9")
		)
		self.assertIn("Client Document Details", html)
		self.assertIn("TEST-CLIENT-DOC-9", html)
		self.assertIn("The client has instructed its own format", html)

	# --- Signatures ----------------------------------------------------------------------------

	def test_a_new_jha_has_four_signature_boxes_with_the_role_of_each_signer(self):
		jha = self.approve(self.full_jha())
		signatures = hse_signatures(jha)
		self.assertEqual(
			[(s["caption"], s["role"]) for s in signatures],
			[
				("Prepared by", "HSE Officer"),
				("Reviewed by", "Branch HSE Head"),
				("Reviewed by", "Branch Head"),
				("Approved by", "HO HSE Team"),
			],
		)
		html = self.printed(jha)
		for text in (
			"Prepared by (HSE Officer)",
			"Reviewed by (Branch HSE Head)",
			"Reviewed by (Branch Head)",
			"Approved by (HO HSE Team)",
		):
			self.assertIn(text, html)

	def test_a_revision_has_three_boxes(self):
		approved = self.approve(self.full_jha())
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, approved.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		revision = self.approve_revision(frappe.get_doc(DOCTYPE, name))
		self.assertEqual(
			[(s["caption"], s["role"]) for s in hse_signatures(revision)],
			[("Prepared by", "HSE Officer"), ("Reviewed by", "Branch Head"), ("Approved by", "HO HSE Team")],
		)

	def test_a_draft_has_boxes_to_sign_by_hand(self):
		signatures = hse_signatures(self.full_jha())
		self.assertEqual([s["signed"] for s in signatures], [True, False, False])

	def test_each_review_level_gets_its_own_box_as_it_is_signed(self):
		jha = self.full_jha()
		act_on(CREATOR, DOCTYPE, jha.name, "Submit for Review")
		act_on(REVIEWER, DOCTYPE, jha.name, "Review and Forward")
		act_on(BRANCH_HEAD, DOCTYPE, jha.name, "Approve and Forward")
		frappe.set_user("Administrator")
		signatures = hse_signatures(frappe.get_doc(DOCTYPE, jha.name))
		self.assertEqual([s["signed"] for s in signatures], [True, True, True, False])
		act_on(HO_TEAM, DOCTYPE, jha.name, "Approve")

	# --- Revision history ----------------------------------------------------------------------

	def test_the_revision_history_is_printed_for_a_revision_only(self):
		approved = self.approve(self.full_jha())
		self.assertNotIn("Revision History", self.printed(approved))
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, approved.name, "Scheduled Review", "TEST: added a hazard")
		frappe.set_user("Administrator")
		html = self.printed(frappe.get_doc(DOCTYPE, name))
		self.assertIn("Revision History", html)
		self.assertIn("TEST: added a hazard", html)
		self.assertIn(">01<", html)

	def test_the_print_format_is_shipped_with_the_app(self):
		fmt = frappe.get_doc("Print Format", DOCTYPE)
		self.assertEqual(fmt.standard, "Yes")
		self.assertEqual(fmt.doc_type, DOCTYPE)
		self.assertEqual(fmt.module, "HSE Health Safety and Environment")
