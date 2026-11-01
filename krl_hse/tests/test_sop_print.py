import frappe
from frappe.utils import add_months, nowdate

from krl_hse.tests.test_sop import (
	BRANCH_HEAD,
	CREATOR,
	DOCTYPE,
	HO_TEAM,
	REVIEWER,
	SOPTestCase,
)
from krl_hse.tests.utils import act_on, sop_step
from krl_hse.utils.controlled_document import start_revision
from krl_hse.utils.printing import hse_format_identity, hse_is_image, hse_ppe_pictures, hse_signatures


class TestSOPPrint(SOPTestCase):
	def printed(self, sop):
		frappe.set_user("Administrator")
		return frappe.get_print(DOCTYPE, sop.name, DOCTYPE)

	def full_sop(self, **kw):
		values = {
			"applicable_to": "TEST: gas cutters",
			"definitions": "TEST: hot work is any work that makes sparks",
			"annexure": "TEST: Annexure A, the cylinder chart",
			"hazards": [
				{"hazard": "TEST: gas leak", "mitigation": "TEST: leak check before use"},
				{"hazard": "TEST: gas leak", "mitigation": "TEST: fire extinguisher at hand"},
				{"hazard": "TEST: sparks", "mitigation": "TEST: screens around the cut"},
			],
			"rules": [
				{"kind": "Do", "rule": "TEST: close the valve after use"},
				{"kind": "Do", "rule": "TEST: wear the apron"},
				{"kind": "Don't", "rule": "TEST: do not use oil on fittings"},
			],
			"steps": [sop_step(), sop_step(activity="TEST: light the torch")],
			"distribution": [{"recipient": "TEST Stores", "copies": 2}],
		}
		values.update(kw)
		return self.new_sop(**values)

	# --- Identity ------------------------------------------------------------------------------

	def test_print_carries_the_format_identity_and_dates(self):
		sop = self.approve(self.full_sop())
		html = self.printed(sop)
		identity = hse_format_identity(DOCTYPE)
		self.assertEqual(identity["format_number"], "KRL/HSE/SOP/1")
		self.assertEqual(identity["format_revision"], "01/24")
		for text in ("KRL/HSE/SOP/1", "01/24", identity["internal_line"], sop.document_number, "Valid Until"):
			self.assertIn(text, html)
		self.assertIn(frappe.utils.formatdate(sop.validity_date), html)
		self.assertIn(frappe.utils.formatdate(sop.first_issue_date), html)

	def test_only_an_unapproved_print_says_so(self):
		sop = self.full_sop()
		self.assertIn("NOT APPROVED", self.printed(sop))
		self.assertNotIn("NOT APPROVED", self.printed(self.approve(sop)))

	def test_a_superseded_print_says_a_later_revision_is_in_force(self):
		sop = self.approve(self.full_sop())
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, sop.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		revision = frappe.get_doc(DOCTYPE, name)
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		self.approve_revision(revision)
		self.assertIn("SUPERSEDED", self.printed(sop))

	# --- Content -------------------------------------------------------------------------------

	def test_every_part_of_the_format_is_printed(self):
		html = self.printed(self.full_sop())
		for text in (
			"Standard Operating Procedure",
			"TEST Gas cutting",
			"TEST: cut steel safely",
			"TEST: all gas cutting at the pit",
			"TEST: gas cutters",
			"TEST: hot work is any work that makes sparks",
			"Mandatory PPE",
			"Hazards Identified and Mandatory Risk Mitigation Actions",
			"TEST: leak check before use",
			"Dos and Don",
			"TEST: close the valve after use",
			"TEST: do not use oil on fittings",
			"Activity (What)",
			"Process, Tools and PPE (How)",
			"TEST: isolate the cylinder valve",
			"TEST: Annexure A, the cylinder chart",
			"Distribution",
			"TEST Stores",
		):
			self.assertIn(text, html)

	def test_the_works_covered_are_listed(self):
		self.assertIn("Works Covered", self.printed(self.full_sop(works=[{"work": "TEST Slag handling"}])))

	def test_a_hazard_with_several_actions_is_printed_once(self):
		html = self.printed(self.full_sop())
		# The steps also name the hazard in their own column, so look at the hazards table only.
		table = html.split("Hazards Identified and Mandatory Risk Mitigation Actions")[1].split(
			"Dos and Don"
		)[0]
		self.assertEqual(table.count("TEST: gas leak"), 1)
		self.assertEqual(table.count('rowspan="2"'), 2)
		self.assertIn("TEST: leak check before use", table)
		self.assertIn("TEST: fire extinguisher at hand", table)
		# Numbered by hazard, not by action.
		self.assertIn('rowspan="2">1<', table)
		self.assertIn('rowspan="1">2<', table)

	def test_dos_and_donts_are_printed_side_by_side(self):
		html = self.printed(self.full_sop())
		self.assertIn("1. TEST: close the valve after use", html)
		self.assertIn("2. TEST: wear the apron", html)
		self.assertIn("1. TEST: do not use oil on fittings", html)

	def test_steps_are_printed_in_order_with_their_references(self):
		html = self.printed(self.full_sop())
		self.assertLess(html.index("TEST: isolate the cylinder valve"), html.index("TEST: light the torch"))
		self.assertIn(">S1<", html)
		self.assertIn(">S2<", html)

	def test_a_sop_without_rules_or_distribution_has_no_empty_section(self):
		html = self.printed(self.new_sop())
		self.assertNotIn("Dos and Don", html)
		self.assertNotIn("Distribution", html)
		self.assertNotIn("Annexure", html)

	def test_typed_text_is_escaped(self):
		sop = self.full_sop()
		frappe.db.set_value(
			"HSE SOP Step", sop.steps[0].name, "activity", "TEST <script>alert(1)</script> step"
		)
		html = self.printed(sop)
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

	# --- PPE pictures --------------------------------------------------------------------------

	def test_ppe_is_listed_with_the_picture_from_the_master(self):
		items = frappe.get_all("HSE PPE Item", pluck="name", limit=2)
		frappe.db.set_value("HSE PPE Item", items[0], "image", "/files/test-ppe-picture.png")
		sop = self.full_sop(ppe=[{"ppe": items[0]}, {"ppe": items[1], "remarks": "TEST: with side shields"}])
		html = self.printed(sop)
		self.assertIn('src="/files/test-ppe-picture.png"', html)
		self.assertIn("TEST: with side shields", html)
		pictures = hse_ppe_pictures(sop)
		self.assertEqual([p["image"] for p in pictures], ["/files/test-ppe-picture.png", ""])

	def test_an_item_without_a_picture_is_still_listed_by_name(self):
		item = frappe.get_all("HSE PPE Item", pluck="name", limit=1)[0]
		frappe.db.set_value("HSE PPE Item", item, "image", None)
		sop = self.full_sop(ppe=[{"ppe": item}])
		name = frappe.db.get_value("HSE PPE Item", item, "ppe_name")
		self.assertIn(name, self.printed(sop))
		self.assertNotIn("<img", self.printed(sop).split("Hazards Identified")[0].split("Mandatory PPE")[1])

	def test_a_ppe_listed_twice_is_shown_once(self):
		item = frappe.get_all("HSE PPE Item", pluck="name", limit=1)[0]
		sop = self.full_sop(ppe=[{"ppe": item}, {"ppe": item}])
		self.assertEqual(len(hse_ppe_pictures(sop)), 1)

	# --- Client details and approval -----------------------------------------------------------

	def test_client_format_and_client_approval_are_printed_only_when_they_apply(self):
		plain = self.printed(self.full_sop())
		self.assertNotIn("Client Document Details", plain)
		self.assertNotIn("Client Approval", plain)

		sop = self.full_sop(
			client_format_applies=1,
			client_document_number="TEST-CLIENT-DOC-9",
			client_approval_required=1,
			client_approval_reference="TEST/CLIENT/77",
			client_approval_date=nowdate(),
		)
		html = self.printed(sop)
		self.assertIn("Client Document Details", html)
		self.assertIn("TEST-CLIENT-DOC-9", html)
		self.assertIn("The client has instructed its own format", html)
		self.assertIn("TEST/CLIENT/77", html)

	def test_a_client_approval_that_is_not_recorded_yet_says_so(self):
		self.assertIn("Not recorded yet", self.printed(self.full_sop(client_approval_required=1)))

	# --- Pictorial SOP -------------------------------------------------------------------------

	def test_a_picture_attached_for_display_is_printed_on_its_own_page(self):
		html = self.printed(self.full_sop(pictorial_file="/files/test-pictorial.png"))
		self.assertIn("Pictorial SOP for Display", html)
		self.assertIn('src="/files/test-pictorial.png"', html)

	def test_a_pictorial_pdf_is_mentioned_not_embedded(self):
		html = self.printed(self.full_sop(pictorial_file="/files/test-pictorial.pdf"))
		self.assertIn("test-pictorial.pdf", html)
		self.assertNotIn('src="/files/test-pictorial.pdf"', html)

	def test_no_pictorial_means_no_page_for_it(self):
		self.assertNotIn("Pictorial SOP", self.printed(self.full_sop()))

	def test_which_files_count_as_pictures(self):
		for path in ("/files/a.png", "/files/B.JPG", "/files/c.jpeg", "/private/files/d.webp"):
			self.assertTrue(hse_is_image(path), path)
		for path in ("/files/a.pdf", "/files/b", "", None):
			self.assertFalse(hse_is_image(path), path)

	# --- Signatures ----------------------------------------------------------------------------

	def test_a_new_sop_has_four_signature_boxes_with_the_role_of_each_signer(self):
		sop = self.approve(self.full_sop())
		signatures = hse_signatures(sop)
		self.assertEqual(
			[(s["caption"], s["role"]) for s in signatures],
			[
				("Prepared by", "HSE Officer"),
				("Reviewed by", "Branch HSE Head"),
				("Reviewed by", "Branch Head"),
				("Approved by", "HO HSE Team"),
			],
		)
		self.assertTrue(all(s["signed"] and s["name"] and s["date"] for s in signatures))

		html = self.printed(sop)
		for text in (
			"Prepared by (HSE Officer)",
			"Reviewed by (Branch HSE Head)",
			"Approved by (HO HSE Team)",
		):
			self.assertIn(text, html)

	def test_a_revision_has_three_boxes(self):
		approved = self.approve(self.full_sop())
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, approved.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		revision = frappe.get_doc(DOCTYPE, name)
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		revision = self.approve_revision(revision)
		self.assertEqual(
			[(s["caption"], s["role"]) for s in hse_signatures(revision)],
			[("Prepared by", "HSE Officer"), ("Reviewed by", "Branch Head"), ("Approved by", "HO HSE Team")],
		)

	def test_a_draft_has_boxes_to_sign_by_hand(self):
		signatures = hse_signatures(self.full_sop())
		self.assertEqual([s["signed"] for s in signatures], [True, False, False])
		self.assertEqual(signatures[1]["role"], "")

	def test_each_review_level_gets_its_own_box_as_it_is_signed(self):
		sop = self.full_sop()
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		act_on(REVIEWER, DOCTYPE, sop.name, "Review and Forward")
		act_on(BRANCH_HEAD, DOCTYPE, sop.name, "Approve and Forward")
		frappe.set_user("Administrator")
		signatures = hse_signatures(frappe.get_doc(DOCTYPE, sop.name))
		self.assertEqual([s["signed"] for s in signatures], [True, True, True, False])

	def test_the_role_is_the_one_the_user_acted_in(self):
		# The head office team can also act as the HSE Head; the box names the role used.
		sop = self.full_sop()
		act_on(CREATOR, DOCTYPE, sop.name, "Submit for Review")
		act_on(REVIEWER, DOCTYPE, sop.name, "Review and Forward")
		act_on(BRANCH_HEAD, DOCTYPE, sop.name, "Approve and Forward")
		act_on(HO_TEAM, DOCTYPE, sop.name, "Approve")
		frappe.set_user("Administrator")
		self.assertEqual(hse_signatures(frappe.get_doc(DOCTYPE, sop.name))[-1]["role"], "HO HSE Team")

	# --- Revision history ----------------------------------------------------------------------

	def test_the_revision_history_is_printed_for_a_revision_only(self):
		approved = self.approve(self.full_sop())
		self.assertNotIn("Revision History", self.printed(approved))
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, approved.name, "Scheduled Review", "TEST: added a step")
		frappe.set_user("Administrator")
		html = self.printed(frappe.get_doc(DOCTYPE, name))
		self.assertIn("Revision History", html)
		self.assertIn("TEST: added a step", html)

	def test_the_print_format_is_shipped_with_the_app(self):
		fmt = frappe.get_doc("Print Format", DOCTYPE)
		self.assertEqual(fmt.standard, "Yes")
		self.assertEqual(fmt.doc_type, DOCTYPE)
		self.assertEqual(fmt.module, "HSE Health Safety and Environment")
