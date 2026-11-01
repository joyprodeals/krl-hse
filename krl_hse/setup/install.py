"""Setup that must exist before the HSE module can be used.

`ensure_setup` runs after install and after every migrate. It only adds what is missing and
never overwrites something KRL has changed.
"""

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

DATA = Path(__file__).parent / "data"

BRANCH_FIELDS = {
	"Branch": [
		{
			"fieldname": "hse_section",
			"fieldtype": "Section Break",
			"label": "HSE",
			"insert_after": "branch",
		},
		{
			"fieldname": "hse_branch_code",
			"fieldtype": "Data",
			"label": "HSE Branch Code",
			"in_list_view": 1,
			"insert_after": "hse_section",
			"description": "Short code used in HSE document numbers, for example J. Must be different for every branch.",
		},
		{
			"fieldname": "hse_is_head_office",
			"fieldtype": "Check",
			"label": "Head Office",
			"in_list_view": 1,
			"insert_after": "hse_branch_code",
			"description": "Tick for the head office. Head office records are not tied to a plant.",
		},
		{
			"fieldname": "hse_disabled",
			"fieldtype": "Check",
			"label": "Disabled for HSE",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "hse_is_head_office",
			"description": (
				"Tick when HSE work at this site has ended. It no longer shows when choosing a branch and no "
				"new HSE record can be made for it. Records already made stay as they are."
			),
		},
		{
			"fieldname": "hse_users_section",
			"fieldtype": "Section Break",
			"label": "People With Access",
			"insert_after": "hse_disabled",
		},
		{
			"fieldname": "hse_users_html",
			"fieldtype": "HTML",
			"label": "People With Access",
			"insert_after": "hse_users_section",
		},
	]
}


def after_install():
	ensure_setup()


def after_migrate():
	ensure_setup()


def ensure_setup():
	create_custom_fields(BRANCH_FIELDS, update=True)
	ensure_roles()
	ensure_link_permissions()
	seed_masters()
	fill_severity_colours()
	seed_risk_matrix()
	ensure_settings_defaults()
	ensure_manage_permissions()
	ensure_workflows()
	frappe.db.commit()


def _load(name):
	with open(DATA / name) as fh:
		return json.load(fh)


def ensure_roles():
	"""Create the system roles of BRD section 14.1 that do not exist yet."""
	for entry in _load("roles.json")["roles"]:
		if frappe.db.exists("Role", entry["role_name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": entry["role_name"],
				"desk_access": 1,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)


def ensure_link_permissions():
	"""Let HSE roles pick records of ERPNext types (see link_permissions.json) without opening them."""
	from frappe.permissions import add_permission

	for doctype, roles in _load("link_permissions.json").items():
		if doctype.startswith("_") or not frappe.db.exists("DocType", doctype):
			continue

		table = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
		for role in roles:
			if not frappe.db.exists("Role", role):
				continue
			if frappe.db.exists(table, {"parent": doctype, "role": role, "permlevel": 0}):
				continue
			add_permission(doctype, role, 0, "select")


def ensure_manage_permissions():
	"""Give the head office roles the rights to manage sites (see manage_permissions.json), once.

	A flag in HSE Settings records that it was done, so a right KRL later takes away is not given back.
	"""
	from frappe.permissions import update_permission_property

	if not frappe.db.exists("DocType", "HSE Settings"):
		return

	settings = frappe.get_doc("HSE Settings")
	if settings.site_rights_loaded:
		return

	for doctype, entry in _load("manage_permissions.json").items():
		if doctype.startswith("_") or not frappe.db.exists("DocType", doctype):
			continue
		for role in entry["roles"]:
			if not frappe.db.exists("Role", role):
				continue
			for right in entry["rights"]:
				update_permission_property(doctype, role, 0, right, 1)

	settings.site_rights_loaded = 1
	settings.save(ignore_permissions=True)


def seed_masters():
	"""Load the starting records of a master, but only while that master is empty.

	After that the records belong to KRL: a record it edits or deletes is not touched again.
	"""
	for doctype, records in _load("masters.json").items():
		if doctype.startswith("_") or not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.count(doctype):
			continue
		for record in records:
			frappe.get_doc({"doctype": doctype, **record}).insert(ignore_permissions=True)


def fill_severity_colours():
	"""Give a severity a starting colour, but only where KRL has not chosen one."""
	if not frappe.db.exists("DocType", "HSE Severity Level"):
		return
	for severity, colour in _load("risk_matrix.json")["colours"].items():
		if frappe.db.exists("HSE Severity Level", severity) and not frappe.db.get_value(
			"HSE Severity Level", severity, "colour"
		):
			frappe.db.set_value("HSE Severity Level", severity, "colour", colour, update_modified=False)


def seed_risk_matrix():
	"""Fill the risk matrix from the starting thresholds, but only while it has no combinations.

	The mapping is a placeholder until KRL confirms it (the Confirmed by KRL tick on HSE Risk Matrix).
	"""
	if not frappe.db.exists("DocType", "HSE Risk Matrix"):
		return

	matrix = frappe.get_doc("HSE Risk Matrix")
	if matrix.cells:
		return

	thresholds = sorted(_load("risk_matrix.json")["thresholds"], key=lambda row: row["max_score"])
	consequences = frappe.get_all("HSE Consequence Level", fields=["name", "level"], order_by="level")
	likelihoods = frappe.get_all("HSE Likelihood Level", fields=["name", "level"], order_by="level")
	if not (consequences and likelihoods):
		return

	for consequence in consequences:
		for likelihood in likelihoods:
			score = consequence.level * likelihood.level
			severity = next((row["severity"] for row in thresholds if score <= row["max_score"]), None)
			if severity and frappe.db.exists("HSE Severity Level", severity):
				matrix.append(
					"cells",
					{"consequence": consequence.name, "likelihood": likelihood.name, "severity": severity},
				)

	matrix.save(ignore_permissions=True)


def ensure_workflows():
	"""Create the starting approval workflows that do not exist yet. Existing ones are left alone."""
	for entry in _load("workflows.json")["workflows"]:
		name = entry["workflow_name"]
		if frappe.db.exists("Workflow", name) or not frappe.db.exists("DocType", entry["document_type"]):
			continue

		for state in entry["states"]:
			if not frappe.db.exists("Workflow State", state["state"]):
				frappe.get_doc(
					{
						"doctype": "Workflow State",
						"workflow_state_name": state["state"],
						"style": state.get("style", ""),
					}
				).insert(ignore_permissions=True)

		for transition in entry["transitions"]:
			if not frappe.db.exists("Workflow Action Master", transition["action"]):
				frappe.get_doc(
					{"doctype": "Workflow Action Master", "workflow_action_name": transition["action"]}
				).insert(ignore_permissions=True)

		doc = frappe.get_doc(
			{
				"doctype": "Workflow",
				"workflow_name": name,
				"document_type": entry["document_type"],
				"is_active": 1,
				"workflow_state_field": "workflow_state",
				"states": [
					{"state": s["state"], "doc_status": s["doc_status"], "allow_edit": role}
					for s in entry["states"]
					for role in s["allow_edit"]
				],
				"transitions": [
					{
						"state": t["state"],
						"action": t["action"],
						"next_state": t["next_state"],
						"allowed": role,
						"allow_self_approval": t.get("allow_self_approval", 1),
					}
					for t in entry["transitions"]
					for role in t["allowed"]
				],
			}
		)
		doc.insert(ignore_permissions=True)


def ensure_settings_defaults():
	"""Fill HSE Settings with the starting values.

	Roles that see all branches are loaded once. Document codes are loaded once for each
	document type, the first time that type exists, so a row KRL deletes is not brought back.
	"""
	if not frappe.db.exists("DocType", "HSE Settings"):
		return

	settings = frappe.get_doc("HSE Settings")
	changed = False

	if not settings.defaults_loaded:
		for entry in _load("roles.json")["roles"]:
			if entry.get("all_branches"):
				settings.append("all_branch_roles", {"role": entry["role_name"]})
		settings.defaults_loaded = 1
		changed = True

	seeded = set((settings.seeded_doctypes or "").split("\n")) - {""}
	for phase, rows in _load("document_codes.json").items():
		if phase.startswith("_"):
			continue
		for row in rows:
			doctype = row["reference_doctype"]
			if doctype in seeded or not frappe.db.exists("DocType", doctype):
				continue
			if not any(r.reference_doctype == doctype for r in settings.document_codes):
				settings.append("document_codes", row)
			seeded.add(doctype)
			changed = True

	if changed:
		settings.seeded_doctypes = "\n".join(sorted(seeded))

	changed = fill_missing_defaults(settings) or changed

	if changed:
		settings.save(ignore_permissions=True)


def fill_missing_defaults(settings):
	"""Give a required setting its default if it is still empty.

	A Single does not receive the default of a field added after it was first saved. Only
	required settings are filled, because those cannot be left empty by KRL on purpose.
	"""
	changed = False
	for df in settings.meta.fields:
		if df.default and df.reqd and not settings.get(df.fieldname):
			settings.set(df.fieldname, df.default)
			changed = True
	return changed
