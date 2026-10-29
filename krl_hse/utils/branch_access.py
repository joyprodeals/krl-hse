"""Branch-level access for HSE records (BRD section 14: branch roles act on their own branch only).

Rules:
  * Administrator, System Manager and any role listed under "Roles That See All Branches" in
    HSE Settings see every branch.
  * Everyone else sees only the branches given to them as User Permissions on Branch.
  * A user who has no branch given sees nothing, so a missing User Permission can never
    open all branches by mistake.

Frappe applies User Permissions to link fields by itself. These hooks add the "sees nothing"
rule and make the branch rule independent of how a User Permission was set up: a User
Permission limited to other document types does not widen access here.

Controlled documents (Method Statement, HIRA, SOP, JHA) have one more rule. Only people who take
part in their approval, meaning a role named in the document's workflow, see a document that is
not approved yet. Everyone else with access to the branch sees approved documents only (BRD 6.1:
"only approved documents are visible for downstream use"). The workflow is the source of the
role list, so changing the workflow in the Desk changes this too.
"""

import frappe
from frappe.model.workflow import get_workflow_name


def get_all_branch_roles():
	settings = frappe.get_cached_doc("HSE Settings")
	return {row.role for row in settings.all_branch_roles}


def sees_all_branches(user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return "System Manager" in roles or bool(roles & get_all_branch_roles())


def get_allowed_branches(user=None, doctype=None):
	"""Branches given to a user. A permission limited to other document types does not count."""
	user = user or frappe.session.user
	rows = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Branch"},
		fields=["for_value", "applicable_for"],
	)
	return sorted({r.for_value for r in rows if not r.applicable_for or r.applicable_for == doctype})


def get_workflow_roles(doctype):
	"""Roles named in a document type's workflow, or None if it has no workflow."""
	name = get_workflow_name(doctype)
	if not name:
		return None
	workflow = frappe.get_cached_doc("Workflow", name)
	return {row.allow_edit for row in workflow.states} | {row.allowed for row in workflow.transitions}


def is_controlled(doctype):
	return doctype in frappe.get_hooks("hse_controlled_doctypes")


def sees_unapproved(user, doctype):
	"""Whether a user takes part in the approval of this document type."""
	if user == "Administrator":
		return True
	workflow_roles = get_workflow_roles(doctype)
	return workflow_roles is None or bool(set(frappe.get_roles(user)) & workflow_roles)


def get_approved_state():
	return frappe.get_cached_doc("HSE Settings").approved_state or "Approved"


def permission_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	conditions = []

	if not sees_all_branches(user):
		branches = get_allowed_branches(user, doctype)
		if not branches:
			return "1=0"
		values = ", ".join(frappe.db.escape(b) for b in branches)
		conditions.append(f"`tab{doctype}`.`branch` in ({values})")

	if is_controlled(doctype) and not sees_unapproved(user, doctype):
		conditions.append(f"`tab{doctype}`.`workflow_state` = {frappe.db.escape(get_approved_state())}")

	return " and ".join(conditions)


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user

	if not sees_all_branches(user):
		branches = get_allowed_branches(user, doc.doctype)
		if not branches:
			return False
		# A record without a branch cannot be judged yet. The mandatory-field check refuses it on save.
		if doc.get("branch") and doc.get("branch") not in branches:
			return False

	if (
		is_controlled(doc.doctype)
		and not doc.is_new()
		and not sees_unapproved(user, doc.doctype)
		and doc.get("workflow_state") != get_approved_state()
	):
		return False

	return True
