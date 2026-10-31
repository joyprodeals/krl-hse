import frappe

from krl_hse.tests.test_method_statement import (
	APPROVER,
	CREATOR,
	REVIEWER,
	MethodStatementTestCase,
)
from krl_hse.tests.utils import act_on
from krl_hse.utils.controlled_document import start_revision
from krl_hse.utils.printing import (
	hse_format_identity,
	hse_group_by,
	hse_group_by_work,
	hse_print_context,
	hse_signatures,
)

DOCTYPE = "HSE Method Statement"


class TestMethodStatementPrint(MethodStatementTestCase):
	def printed(self, ms):
		frappe.set_user("Administrator")
		return frappe.get_print(DOCTYPE, ms.name, DOCTYPE)

	# --- Format identity ---------------------------------------------------------------------

	def test_print_carries_the_format_identity(self):
		ms = self.approve(self.new_ms())
		html = self.printed(ms)
		identity = hse_format_identity(DOCTYPE)
		self.assertEqual(identity["format_number"], "KRL/HSE/MS/01")
		self.assertEqual(identity["format_revision"], "01/24")
		self.assertIn("KRL/HSE/MS/01", html)
		self.assertIn("01/24", html)
		self.assertIn(identity["internal_line"], html)
		self.assertIn(ms.document_number, html)

	def test_identity_and_internal_line_follow_the_settings(self):
		settings = frappe.get_doc("HSE Settings")
		row = next(r for r in settings.document_codes if r.reference_doctype == DOCTYPE)
		old = (row.format_number, row.format_revision, settings.internal_document_line)
		try:
			row.format_number, row.format_revision = "TEST/FMT/9", "07/30"
			settings.internal_document_line = "TEST internal line"
			settings.save(ignore_permissions=True)
			html = self.printed(self.new_ms())
			self.assertIn("TEST/FMT/9", html)
			self.assertIn("07/30", html)
			self.assertIn("TEST internal line", html)
			self.assertNotIn("KRL/HSE/MS/01", html)
		finally:
			row.format_number, row.format_revision, settings.internal_document_line = old
			settings.save(ignore_permissions=True)

	# --- Status line ---------------------------------------------------------------------------

	def test_only_an_unapproved_print_says_so(self):
		ms = self.new_ms()
		self.assertIn("NOT APPROVED", self.printed(ms))
		self.assertNotIn("NOT APPROVED", self.printed(self.approve(ms)))

	def test_a_superseded_print_says_a_later_revision_is_in_force(self):
		ms = self.approve(self.new_ms())
		frappe.set_user(CREATOR)
		rev = start_revision(DOCTYPE, ms.name, "Client Requirement", "TEST: change")
		self.approve(frappe.get_doc(DOCTYPE, rev))
		self.assertIn("SUPERSEDED", self.printed(ms))

	# --- Signatures ----------------------------------------------------------------------------

	def test_signatures_are_read_from_the_sign_offs(self):
		ms = self.approve(self.new_ms())
		prepared, reviewed, approved = hse_signatures(ms)
		self.assertEqual(
			[prepared["caption"], reviewed["caption"], approved["caption"]],
			["Prepared by", "Reviewed by", "Approved by"],
		)
		for sign, user in ((prepared, CREATOR), (reviewed, REVIEWER), (approved, APPROVER)):
			self.assertTrue(sign["signed"])
			self.assertEqual(sign["name"], frappe.get_cached_value("User", user, "full_name"))
			self.assertTrue(sign["date"])

	def test_a_draft_has_boxes_to_sign_by_hand(self):
		ms = self.new_ms()
		signatures = hse_signatures(ms)
		self.assertEqual([s["caption"] for s in signatures], ["Prepared by", "Reviewed by", "Approved by"])
		self.assertEqual([s["signed"] for s in signatures], [True, False, False])
		self.assertEqual(signatures[1]["name"], "")

	def test_sending_back_is_not_a_review_and_the_latest_submission_is_prepared_by(self):
		ms = self.new_ms()
		act_on(CREATOR, DOCTYPE, ms.name, "Submit for Review")
		act_on(REVIEWER, DOCTYPE, ms.name, "Send Back", recommendations="TEST: add detail")
		act_on(CREATOR, DOCTYPE, ms.name, "Submit for Review")
		frappe.set_user("Administrator")
		prepared, reviewed, approved = hse_signatures(frappe.get_doc(DOCTYPE, ms.name))
		self.assertTrue(prepared["signed"])
		self.assertEqual(prepared["name"], frappe.get_cached_value("User", CREATOR, "full_name"))
		self.assertFalse(reviewed["signed"])
		self.assertFalse(approved["signed"])

	def test_each_review_level_gets_its_own_box(self):
		ms = self.new_ms()
		act_on(CREATOR, DOCTYPE, ms.name, "Submit for Review")
		act_on(REVIEWER, DOCTYPE, ms.name, "Review and Forward")
		frappe.set_user("Administrator")
		signatures = hse_signatures(frappe.get_doc(DOCTYPE, ms.name))
		self.assertEqual([s["caption"] for s in signatures], ["Prepared by", "Reviewed by", "Approved by"])
		self.assertEqual([s["signed"] for s in signatures], [True, True, False])

	# --- Revision history ----------------------------------------------------------------------

	def test_revision_history_lists_every_revision_up_to_this_one(self):
		ms = self.approve(self.new_ms())
		frappe.set_user(CREATOR)
		first = frappe.get_doc(
			DOCTYPE, start_revision(DOCTYPE, ms.name, "Client Requirement", "TEST: first change")
		)
		first = self.approve(first)
		frappe.set_user(CREATOR)
		second = frappe.get_doc(
			DOCTYPE, start_revision(DOCTYPE, first.name, "Audit Recommendation", "TEST: second change")
		)
		frappe.set_user("Administrator")

		history = hse_print_context(second)["revisions"]
		self.assertEqual([row["revision_number"] for row in history], [0, 1, 2])
		self.assertEqual(history[1]["remark"], "TEST: first change")
		self.assertEqual(history[2]["trigger"], "Audit Recommendation")
		# Revision 1 is approved and dated, revision 2 is not yet.
		self.assertTrue(history[1]["date"])
		self.assertEqual(history[2]["date"], "")

		# The first revision's print does not show the later ones.
		self.assertEqual([r["revision_number"] for r in hse_print_context(first)["revisions"]], [0, 1])
		self.assertIn("TEST: second change", self.printed(second))
		self.assertNotIn("Revision History", self.printed(ms))

	# --- Content -------------------------------------------------------------------------------

	def test_works_come_first_then_the_common_names(self):
		ms = self.new_ms(
			works=[{"work_name": "TEST A"}, {"work_name": "TEST B"}],
			operations=[
				{"work": "TEST B", "operation": "TEST b1"},
				{"work": "TEST A", "operation": "TEST a1"},
				{"work": "TEST A", "operation": "TEST a2"},
			],
			equipment=[
				{"work": "General", "equipment": "TEST bus", "qty": 1},
				{"work": "TEST B", "equipment": "TEST pump", "qty": 2},
			],
		)
		self.assertEqual([g["work"] for g in hse_group_by_work(ms, "operations")], ["TEST A", "TEST B"])
		self.assertEqual([len(g["rows"]) for g in hse_group_by_work(ms, "operations")], [2, 1])
		self.assertEqual([g["work"] for g in hse_group_by_work(ms, "equipment")], ["TEST B", "General"])

	def test_ppe_is_grouped_by_activity_with_basic_first(self):
		ms = self.new_ms()
		ms.append("ppe", {"activity": "Gas cutting", "ppe": ms.ppe[0].ppe})
		ms.save(ignore_permissions=True)
		groups = hse_group_by(ms, "ppe", "activity")
		self.assertEqual(groups[0]["key"], "Basic")
		self.assertEqual(groups[-1]["key"], "Gas cutting")

	def test_sops_and_hazards_are_printed_work_wise_before_the_emergency_numbers(self):
		ms = self.new_ms(
			sops=[
				{"work": "TEST Slag handling", "sop_reference": "TEST/SOP/01"},
				{"work": "TEST Slag handling", "sop_reference": "TEST/SOP/02"},
			],
			hazards=[
				{
					"work": "TEST Slag handling",
					"hazard_risk": "TEST: hot metal, fire",
					"reference_document": "TEST/HIRA/01",
				}
			],
		)
		html = self.printed(ms)
		for text in ("TEST/SOP/01", "TEST/SOP/02", "TEST: hot metal, fire", "TEST/HIRA/01"):
			self.assertIn(text, html)
		sop_heading = html.index("Standard Operating Procedures")
		hazard_heading = html.index("Potential Hazard and Risks")
		self.assertLess(html.index("PPE"), sop_heading)
		self.assertLess(sop_heading, hazard_heading)
		self.assertLess(hazard_heading, html.index("Emergency Numbers"))
		self.assertEqual([g["work"] for g in hse_group_by_work(ms, "sops")], ["TEST Slag handling"])
		self.assertEqual(len(hse_group_by_work(ms, "sops")[0]["rows"]), 2)

	def test_a_print_without_sops_or_hazards_has_no_empty_section(self):
		html = self.printed(self.new_ms())
		self.assertNotIn("Standard Operating Procedures", html)
		self.assertNotIn("Potential Hazard and Risks", html)

	def test_typed_text_is_escaped_in_the_print(self):
		ms = self.new_ms()
		# Written straight to the database, as the form would have stripped the tags on save.
		frappe.db.set_value(
			"HSE MS Operation", ms.operations[0].name, "operation", "TEST <script>alert(1)</script> step"
		)
		html = self.printed(ms)
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

	def test_the_print_format_is_shipped_with_the_app(self):
		fmt = frappe.get_doc("Print Format", DOCTYPE)
		self.assertEqual(fmt.standard, "Yes")
		self.assertEqual(fmt.doc_type, DOCTYPE)
		self.assertEqual(fmt.module, "HSE Health Safety and Environment")
