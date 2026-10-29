"""Helpers for the HSE print formats.

The print format templates are Jinja. Every function defined in this module is available in them
by its own name (see `jinja` in hooks.py), so the layout files stay free of logic and of anything
KRL may want to change:

  * the format number and revision (`format_number`, `format_revision`) come from the
    document code row in HSE Settings,
  * the line "This is an internal document and not for circulation" is a setting too,
  * "Prepared by", "Reviewed by" and "Approved by" are read from the Sign-offs table of the
    document, so each signature is a recorded confirmation by a named user with a date
    (BRD 6.9.3), never a name typed on the form.
"""

import frappe
from frappe import _
from frappe.utils import formatdate, get_fullname


def hse_company_name():
	"""The company printed in the header: the default company of the site, else the first one."""
	company = frappe.defaults.get_global_default("company") or next(
		iter(frappe.get_all("Company", pluck="name", order_by="creation asc", limit=1)), None
	)
	if not company:
		return ""
	return frappe.db.get_value("Company", company, "company_name") or company


def hse_format_identity(doctype):
	"""Format number, format revision and the internal-document line for a document type."""
	settings = frappe.get_cached_doc("HSE Settings")
	row = next((r for r in settings.document_codes if r.reference_doctype == doctype), None)
	return {
		"format_number": (row.format_number if row else "") or "",
		"format_revision": (row.format_revision if row else "") or "",
		"internal_line": settings.internal_document_line or "",
	}


def hse_print_context(doc):
	"""What the header, footer and signature block of a controlled document print needs."""
	from krl_hse.utils.controlled_document import get_approved_state, get_superseded_state

	state = doc.get("workflow_state") or ""
	identity = hse_format_identity(doc.doctype)
	return {
		**identity,
		"company": hse_company_name(),
		"state": state,
		"is_approved": state == get_approved_state(),
		"is_superseded": state == get_superseded_state(),
		"signatures": hse_signatures(doc),
		"revisions": hse_revision_history(doc),
	}


def _designation(user):
	return frappe.db.get_value("Employee", {"user_id": user}, "designation") or ""


def _signature(caption, row=None):
	if row is None:
		return {"caption": caption, "name": "", "designation": "", "date": "", "signed": False}
	return {
		"caption": caption,
		"name": row.full_name or get_fullname(row.user),
		"designation": _designation(row.user),
		"date": formatdate(row.signed_on) if row.signed_on else "",
		"signed": True,
	}


def hse_signatures(doc):
	"""Prepared by, Reviewed by and Approved by, from the recorded sign-offs.

	* Prepared by is whoever last sent the document for review. A draft that has not been sent yet
	  shows its creator.
	* Reviewed by is every intermediate forward after that. While the document is not approved and has
	  no review yet, one empty box is shown so the printout can be signed by hand.
	* Approved by is the last approval. Until then the box is empty.
	"""
	from krl_hse.utils.controlled_document import get_approved_state, get_settings, get_workflow

	rows = list(doc.get("sign_offs") or [])
	if not rows:
		return [_signature(_("Prepared by")), _signature(_("Reviewed by")), _signature(_("Approved by"))]

	workflow = get_workflow(doc.doctype)
	start_states = {get_settings().sent_back_state}
	if workflow and workflow.states:
		start_states.add(workflow.states[0].state)
	approved = get_approved_state()

	submitted = None
	for index, row in enumerate(rows):
		if row.from_state in start_states and row.to_state not in start_states:
			submitted = index

	approval = None
	for index, row in enumerate(rows):
		if row.to_state == approved and row.from_state != approved:
			approval = index

	if submitted is None:
		prepared = _signature(_("Prepared by"), rows[0])
		reviews = []
	else:
		prepared = _signature(_("Prepared by"), rows[submitted])
		reviews = [
			_signature(_("Reviewed by"), row)
			for index, row in enumerate(rows[submitted + 1 :], start=submitted + 1)
			if index != approval and row.to_state not in start_states and row.to_state != approved
		]

	if not reviews and approval is None:
		reviews = [_signature(_("Reviewed by"))]

	return [
		prepared,
		*reviews,
		_signature(_("Approved by"), rows[approval] if approval is not None else None),
	]


def hse_revision_history(doc):
	"""Every revision of this document number, oldest first, for the revision table."""
	if not doc.get("document_number"):
		return []

	rows = frappe.get_all(
		doc.doctype,
		filters={"document_number": doc.document_number, "revision_number": ("<=", doc.revision_number or 0)},
		fields=[
			"name",
			"revision_number",
			"first_issue_date",
			"revision_date",
			"revision_trigger",
			"revision_remark",
			"workflow_state",
		],
		order_by="revision_number asc",
	)
	history = []
	for row in rows:
		date = row.first_issue_date if not row.revision_number else row.revision_date
		history.append(
			{
				"revision_number": row.revision_number or 0,
				"date": formatdate(date) if date else "",
				"trigger": row.revision_trigger or "",
				"remark": row.revision_remark or "",
				"name": row.name,
				"state": row.workflow_state or "",
			}
		)
	return history


def hse_group_by_work(doc, table):
	"""Rows of a table that has a `work` column, grouped by work.

	The works come in the order of the Works table of the document, then the other names (General,
	Administration, ...) in the order they first appear.
	"""
	order = [row.work_name for row in doc.get("works") or []]
	groups = {}
	for row in doc.get(table) or []:
		groups.setdefault(row.work or "", []).append(row)

	out = [{"work": work, "rows": groups.pop(work)} for work in order if work in groups]
	out += [{"work": work, "rows": rows} for work, rows in groups.items()]
	return out


def hse_group_by(doc, table, fieldname):
	"""Rows of a table grouped by the value of one field, in order of first appearance."""
	groups = {}
	for row in doc.get(table) or []:
		groups.setdefault(row.get(fieldname) or "", []).append(row)
	return [{"key": key, "rows": rows} for key, rows in groups.items()]


def hse_work_description(doc, work):
	"""The description written against a work in the Works table, if any."""
	return next(
		(row.description for row in doc.get("works") or [] if row.work_name == work and row.description), ""
	)
