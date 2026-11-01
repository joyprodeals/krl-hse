import frappe

from krl_hse.tests.test_hira import HIRATestCase
from krl_hse.tests.utils import hira_line
from krl_hse.utils.controlled_document import start_revision
from krl_hse.utils.printing import hse_employee_name, hse_format_identity, hse_risk_legend, hse_signatures

DOCTYPE = "HSE HIRA"


class TestHIRAPrint(HIRATestCase):
	def printed(self, hira):
		frappe.set_user("Administrator")
		return frappe.get_print(DOCTYPE, hira.name, DOCTYPE)

	def test_print_carries_the_format_identity(self):
		hira = self.new_hira()
		html = self.printed(hira)
		identity = hse_format_identity(DOCTYPE)
		self.assertEqual(identity["format_number"], "KRL/HSE/HIRA/1")
		self.assertEqual(identity["format_revision"], "01/24")
		self.assertIn("KRL/HSE/HIRA/1", html)
		self.assertIn("01/24", html)
		self.assertIn(identity["internal_line"], html)
		self.assertIn(hira.document_number, html)

	def test_the_sheet_is_landscape(self):
		self.assertIn("orientation: Landscape", self.printed(self.new_hira()))

	def test_every_column_of_the_format_is_printed(self):
		hira = self.new_hira(
			lines=[
				hira_line(
					job="TEST Job 7",
					routine="Non-Routine",
					activity_category="Equipment",
					activity="TEST activity text",
					hazard="TEST hazard text",
					hazardous_event="TEST event text",
					cause="TEST cause text",
					consequence_impact="TEST impact text",
					existing_safeguard="TEST safeguard text",
					recommendation="TEST recommendation text",
				)
			]
		)
		html = self.printed(hira)
		for text in (
			"TEST Job 7",
			"Non-Routine",
			"Equipment",
			"TEST activity text",
			"TEST hazard text",
			"Physical",
			"TEST event text",
			"TEST cause text",
			"TEST impact text",
			"People",
			"TEST safeguard text",
			"TEST recommendation text",
			"C2 Minor",
			"Possible",
			"C1 Insignificant",
			"Rare",
		):
			self.assertIn(text, html)
		self.assertIn("Risk Rating", html)
		self.assertIn("Residual Risk Rating", html)

	def test_severity_is_printed_before_and_after_the_controls(self):
		html = self.printed(self.new_hira())
		self.assertIn('<td class="hse-risk">III</td>', html)
		self.assertIn('<td class="hse-risk">I</td>', html)

	def test_line_references_are_printed_for_the_control_table_to_refer_to(self):
		html = self.printed(self.new_hira(lines=[hira_line(), hira_line()]))
		self.assertIn('<td class="hse-c">L1</td>', html)
		self.assertIn('<td class="hse-c">L2</td>', html)

	def test_control_measures_are_printed_only_when_there_are_some(self):
		self.assertNotIn("Control Measures", self.printed(self.new_hira()))
		hira = self.new_hira(
			controls=[
				{
					"line_ref": "L1",
					"measure_type": "Existing",
					"control": "TEST barricade text",
					"hierarchy_level": "Isolation",
				}
			]
		)
		html = self.printed(hira)
		self.assertIn("Control Measures", html)
		self.assertIn("TEST barricade text", html)
		self.assertIn("Isolation", html)

	def test_the_client_block_is_printed_only_when_the_client_format_applies(self):
		self.assertNotIn("Client Document Details", self.printed(self.new_hira()))
		hira = self.new_hira(
			client_format_applies=1,
			client_format_reference="CLIENT/HIRA/7",
			client_department="TEST Dept",
			client_document_number="CL-DOC-42",
		)
		html = self.printed(hira)
		self.assertIn("Client Document Details", html)
		for text in ("CLIENT/HIRA/7", "TEST Dept", "CL-DOC-42"):
			self.assertIn(text, html)

	def test_only_an_unapproved_print_says_so(self):
		hira = self.new_hira()
		self.assertIn("NOT APPROVED", self.printed(hira))
		self.assertNotIn("NOT APPROVED", self.printed(self.approve(hira)))

	def test_the_severity_scale_is_printed_from_the_masters(self):
		html = self.printed(self.new_hira())
		legend = hse_risk_legend()
		self.assertEqual(
			[r.name for r in legend["rows"]], [f"Severity {n}" for n in ("I", "II", "III", "IV", "V")]
		)
		self.assertEqual(legend["rows"][-1].timeline, "Immediate")
		self.assertIn("Stop all work", html)

	def test_the_provisional_note_follows_the_confirmed_tick(self):
		self.assertIn("provisional", self.printed(self.new_hira()))

		matrix = frappe.get_doc("HSE Risk Matrix")
		matrix.confirmed_by_krl = 1
		matrix.save(ignore_permissions=True)

		def untick():
			again = frappe.get_doc("HSE Risk Matrix")
			again.confirmed_by_krl = 0
			again.save(ignore_permissions=True)

		self.addCleanup(untick)
		self.assertNotIn("provisional", self.printed(self.new_hira()))

	def test_signatures_come_from_the_sign_offs(self):
		hira = self.approve(self.new_hira())
		sign = {s["caption"]: s for s in hse_signatures(hira)}
		self.assertTrue(sign["Prepared by"]["signed"])
		self.assertTrue(sign["Reviewed by"]["signed"])
		self.assertTrue(sign["Approved by"]["signed"])
		html = self.printed(hira)
		for caption in ("Prepared by", "Reviewed by", "Approved by"):
			self.assertIn(caption, html)

	def test_a_draft_has_empty_boxes_to_sign_by_hand(self):
		sign = {s["caption"]: s for s in hse_signatures(self.new_hira())}
		self.assertFalse(sign["Approved by"]["signed"])

	def test_a_revision_prints_its_history(self):
		approved = self.approve(self.new_hira())
		name = start_revision(DOCTYPE, approved.name, "CAPA Finding", "TEST: history text")
		revision = self.approve(frappe.get_doc(DOCTYPE, name))
		html = self.printed(revision)
		self.assertIn("Revision History", html)
		self.assertIn("TEST: history text", html)
		self.assertIn("Original issue", html)

	def test_a_name_that_is_not_an_employee_is_printed_as_given(self):
		self.assertEqual(hse_employee_name("TEST-NO-SUCH-EMP"), "TEST-NO-SUCH-EMP")
		self.assertEqual(hse_employee_name(""), "")

	def test_responsible_person_and_date_are_printed(self):
		hira = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"branch": "TEST Athagarh",
				"method_statement": self.ms.name,
				"area": self.area.name,
				"lines": [hira_line()],
				"controls": [
					{
						"line_ref": "L1",
						"measure_type": "Additional",
						"control": "TEST guard rail",
						"hierarchy_level": "Engineering Control",
						"responsible": "TEST-NO-SUCH-EMP",
						"target_date": "2027-01-15",
					}
				],
			}
		)
		hira.flags.ignore_links = True
		hira.insert(ignore_permissions=True)
		html = self.printed(hira)
		self.assertIn("TEST-NO-SUCH-EMP", html)
		self.assertIn(frappe.utils.formatdate("2027-01-15"), html)
