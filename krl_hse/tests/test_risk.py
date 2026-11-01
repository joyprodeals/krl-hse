import frappe
from frappe.tests import IntegrationTestCase

from krl_hse.setup.install import seed_risk_matrix
from krl_hse.utils.risk import (
	get_risk_matrix,
	matrix_preview_html,
	severity_for,
	severity_map,
	text_colour,
)

IGNORE_TEST_RECORD_DEPENDENCIES = []


class TestRiskMasters(IntegrationTestCase):
	def test_starting_lists_are_loaded(self):
		self.assertEqual(
			frappe.get_all("HSE Hazard Category", pluck="name", order_by="name"),
			["Biological", "Chemical", "Ergonomic", "Physical", "Psychosocial"],
		)
		self.assertEqual(
			frappe.get_all("HSE Impact Area", pluck="name", order_by="name"),
			["Asset", "Community", "Environment", "People"],
		)
		self.assertEqual(frappe.db.count("HSE Activity Category"), 8)

	def test_hierarchy_of_control_runs_from_elimination_to_ppe(self):
		rows = frappe.get_all(
			"HSE Hierarchy of Control", fields=["name", "is_ppe"], order_by="control_order asc"
		)
		self.assertEqual(rows[0].name, "Elimination")
		self.assertEqual(rows[-1].name, "PPE")
		self.assertEqual([r.name for r in rows if r.is_ppe], ["PPE"])

	def test_scales_have_five_levels_with_handbook_definitions(self):
		likelihoods = frappe.get_all(
			"HSE Likelihood Level", fields=["name", "level", "definition"], order_by="level"
		)
		self.assertEqual(
			[r.name for r in likelihoods], ["Rare", "Unlikely", "Possible", "Very Likely", "Certain"]
		)
		self.assertEqual(likelihoods[0].definition, "Never occurred earlier in the workplace")
		consequences = frappe.get_all("HSE Consequence Level", pluck="name", order_by="level")
		self.assertEqual(len(consequences), 5)
		self.assertTrue(consequences[0].startswith("C1"))

	def test_a_scale_level_cannot_be_used_twice(self):
		doc = frappe.get_doc({"doctype": "HSE Likelihood Level", "likelihood_label": "TEST Twin", "level": 3})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_a_scale_level_must_be_positive(self):
		doc = frappe.get_doc(
			{"doctype": "HSE Consequence Level", "consequence_label": "TEST Zero", "level": 0}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_hierarchy_order_must_be_positive(self):
		doc = frappe.get_doc(
			{"doctype": "HSE Hierarchy of Control", "control_level": "TEST Rank", "control_order": 0}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)


class TestRiskMatrix(IntegrationTestCase):
	def setUp(self):
		self.consequences = frappe.get_all("HSE Consequence Level", pluck="name", order_by="level")
		self.likelihoods = frappe.get_all("HSE Likelihood Level", pluck="name", order_by="level")

	def test_every_pair_has_a_severity(self):
		cells = severity_map()
		self.assertEqual(len(cells), len(self.consequences) * len(self.likelihoods))
		for c in self.consequences:
			for l in self.likelihoods:
				self.assertIn(cells[(c, l)], frappe.get_all("HSE Severity Level", pluck="name"))

	def test_corners_of_the_starting_matrix(self):
		self.assertEqual(severity_for(self.consequences[0], self.likelihoods[0]), "Severity I")
		self.assertEqual(severity_for(self.consequences[-1], self.likelihoods[-1]), "Severity V")

	def test_severity_never_falls_as_either_scale_rises(self):
		level = {r.name: r.level for r in frappe.get_all("HSE Severity Level", fields=["name", "level"])}
		for ci, c in enumerate(self.consequences):
			for li, l in enumerate(self.likelihoods):
				here = level[severity_for(c, l)]
				if ci:
					self.assertGreaterEqual(here, level[severity_for(self.consequences[ci - 1], l)])
				if li:
					self.assertGreaterEqual(here, level[severity_for(c, self.likelihoods[li - 1])])

	def test_an_empty_rating_has_no_severity(self):
		self.assertIsNone(severity_for(None, self.likelihoods[0]))
		self.assertIsNone(severity_for(self.consequences[0], ""))

	def test_the_matrix_can_be_changed_and_the_change_is_used(self):
		matrix = frappe.get_doc("HSE Risk Matrix")
		original = [dict(c=r.consequence, l=r.likelihood, s=r.severity) for r in matrix.cells]
		self.addCleanup(self.restore, original)

		pair = (self.consequences[0], self.likelihoods[0])
		self.assertEqual(severity_for(*pair), "Severity I")
		for row in matrix.cells:
			if (row.consequence, row.likelihood) == pair:
				row.severity = "Severity V"
		matrix.save(ignore_permissions=True)

		self.assertEqual(severity_for(*pair), "Severity V")

	def restore(self, original):
		matrix = frappe.get_doc("HSE Risk Matrix")
		matrix.cells = []
		for row in original:
			matrix.append("cells", {"consequence": row["c"], "likelihood": row["l"], "severity": row["s"]})
		matrix.save(ignore_permissions=True)

	def test_the_same_pair_cannot_be_listed_twice(self):
		matrix = frappe.get_doc("HSE Risk Matrix")
		matrix.append(
			"cells",
			{
				"consequence": self.consequences[0],
				"likelihood": self.likelihoods[0],
				"severity": "Severity II",
			},
		)
		with self.assertRaises(frappe.ValidationError):
			matrix.save(ignore_permissions=True)

	def test_loading_the_starting_data_again_changes_nothing(self):
		before = frappe.get_doc("HSE Risk Matrix").cells
		seed_risk_matrix()
		self.assertEqual(len(frappe.get_doc("HSE Risk Matrix").cells), len(before))

	def test_the_browser_gets_cells_severities_and_colours(self):
		data = get_risk_matrix()
		pair = f"{self.consequences[-1]}|{self.likelihoods[-1]}"
		self.assertEqual(data["cells"][pair], "Severity V")
		self.assertTrue(data["severities"]["Severity V"]["colour"].startswith("#"))
		self.assertEqual(data["severities"]["Severity V"]["stops_work"], 1)
		self.assertEqual(len(data["consequences"]), 5)
		self.assertIn("confirmed", data)

	def test_the_preview_shows_every_severity_cell(self):
		html = matrix_preview_html()
		self.assertEqual(html.count("<td"), len(self.consequences) * len(self.likelihoods))
		self.assertIn("Severity V", html)

	def test_text_is_dark_on_light_and_light_on_dark(self):
		self.assertEqual(text_colour("#fbc02d"), "#000000")
		self.assertEqual(text_colour("#7cb342"), "#000000")
		self.assertEqual(text_colour("#b71c1c"), "#ffffff")
		self.assertEqual(text_colour(None), "#000000")
