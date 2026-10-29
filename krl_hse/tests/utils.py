"""Helpers shared by the app's tests."""

import frappe


def make_branch(name, code, head_office=0):
	if frappe.db.exists("Branch", name):
		frappe.db.set_value("Branch", name, {"hse_branch_code": code, "hse_is_head_office": head_office})
		return frappe.get_doc("Branch", name)
	return frappe.get_doc(
		{"doctype": "Branch", "branch": name, "hse_branch_code": code, "hse_is_head_office": head_office}
	).insert(ignore_permissions=True)


def set_document_code(doctype, code, number_format=""):
	"""Put a document code row into HSE Settings for a test."""
	settings = frappe.get_doc("HSE Settings")
	settings.document_codes = [r for r in settings.document_codes if r.reference_doctype != doctype]
	settings.append(
		"document_codes",
		{"reference_doctype": doctype, "document_code": code, "number_format": number_format},
	)
	settings.save(ignore_permissions=True)
	frappe.clear_cache(doctype="HSE Settings")
	return settings


def make_work_order(branch, job_code, **kw):
	values = {
		"doctype": "HSE Work Order",
		"branch": branch,
		"job_code": job_code,
		"work_title": f"TEST work {job_code}",
		"client_name": "TEST Client",
	}
	values.update(kw)
	return frappe.get_doc(values).insert(ignore_permissions=True)


def make_area(branch, area_name, **kw):
	values = {"doctype": "HSE Workplace Area", "branch": branch, "area_name": area_name}
	values.update(kw)
	return frappe.get_doc(values).insert(ignore_permissions=True)


def current_fy():
	"""Financial year label for today, as HSE Settings is set up."""
	from frappe.utils import nowdate

	from krl_hse.utils.numbering import financial_year_label, month_number

	settings = frappe.get_cached_doc("HSE Settings")
	return financial_year_label(nowdate(), month_number(settings.fy_start_month), settings.fy_label_format)


def make_user(email, roles, branches=(), first_name="TEST"):
	"""A test user with the given roles and branch User Permissions. Never emails anyone."""
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"send_welcome_email": 0,
			"enabled": 1,
			"roles": [{"role": r} for r in roles],
		}
	)
	user.flags.no_welcome_mail = True
	user.insert(ignore_permissions=True)

	for branch in branches:
		frappe.get_doc(
			{"doctype": "User Permission", "user": email, "allow": "Branch", "for_value": branch}
		).insert(ignore_permissions=True)
	return user


def make_method_statement(branch, work_order, **kw):
	values = {"doctype": "HSE Method Statement", "branch": branch, "work_order": work_order}
	values.update(kw)
	return frappe.get_doc(values).insert(ignore_permissions=True)


def method_statement_content(work="TEST Slag handling"):
	"""The least a Method Statement needs before it can be sent for review."""
	return {
		"works": [{"work_name": work}],
		"operations": [{"work": work, "operation": "TEST: position the loader at the pit"}],
	}


def act_on(user, doctype, name, action, **values):
	"""Apply a workflow action as a user, saving any values first, as the form does."""
	from frappe.model.workflow import apply_workflow

	frappe.set_user(user)
	doc = frappe.get_doc(doctype, name)
	if values:
		doc.update(values)
		doc.save()
	return apply_workflow(doc, action)
