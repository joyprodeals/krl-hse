import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

SIDEBAR = (
	Path(frappe.get_app_path("krl_hse"))
	/ "hse_health_safety_and_environment"
	/ "sidebar"
	/ "hse"
	/ "hse.json"
)
MODULE = "HSE Health Safety and Environment"


class TestSidebar(IntegrationTestCase):
	def linked(self):
		items = json.loads(SIDEBAR.read_text())["items"]
		return [row["link_to"] for row in items if row["type"] == "Link"]

	def test_every_link_goes_to_a_real_document_type(self):
		for doctype in self.linked():
			self.assertTrue(frappe.db.exists("DocType", doctype), doctype)

	def test_every_document_type_of_the_module_is_in_the_sidebar(self):
		"""A new master or document must be given a place in the sidebar, or this fails."""
		linked = set(self.linked())
		missing = [
			name
			for name in frappe.get_all("DocType", filters={"module": MODULE, "istable": 0}, pluck="name")
			if name not in linked
		]
		self.assertEqual(missing, [], f"Add these to sidebar/hse/hse.json: {missing}")

	def test_nothing_is_listed_twice(self):
		linked = self.linked()
		self.assertEqual(len(linked), len(set(linked)))

	def test_sections_come_before_their_links(self):
		items = json.loads(SIDEBAR.read_text())["items"]
		self.assertEqual(items[0]["type"], "Section Break")
		for row in items:
			if row["type"] == "Link" and row["child"]:
				self.assertTrue(any(i["type"] == "Section Break" for i in items[: items.index(row)]))
