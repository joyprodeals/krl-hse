"""Review dates, review status and reminders for documents that are reviewed on a schedule.

A document type is reviewed on a schedule when it is named in `hse_review_date_fields` (hooks.py), with
the date field that says when. For a HIRA that is `next_review_date`, worked out from the review period
of its document code when it is approved. For a SOP it is `validity_date`, which the author gives.

Once a day an approved document is marked

  * Current      the date is more than "Review Reminder (Days)" away,
  * Review Due   the date is that close, or today,
  * Overdue      the date has passed,

and, when it is due or overdue, the Branch HSE Head of its branch is given a task and a notice.
Each stage reminds once, so closing the task does not bring it back the next day.

A review ends with a revision (trigger "Scheduled Review") that is approved again. That is how a
document that needs no change is renewed, and it gives the re-approval the handbook asks for.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, formatdate, getdate, nowdate

from krl_hse.utils.controlled_document import get_approved_state, get_settings

CURRENT = "Current"
DUE = "Review Due"
OVERDUE = "Overdue"

REMINDER_ROLE = "Branch HSE Head"
FALLBACK_ROLE = "HSE Head"


def review_date_field(doctype):
	"""The date field that says when a document type is next reviewed, or None."""
	field = (frappe.get_hooks("hse_review_date_fields") or {}).get(doctype)
	if isinstance(field, list | tuple):
		field = field[-1] if field else None
	return field


def review_doctypes():
	return list((frappe.get_hooks("hse_review_date_fields") or {}).keys())


def review_status_for(review_date, today=None):
	"""Current, Review Due or Overdue for a review date. Blank when there is no date."""
	if not review_date:
		return ""
	today = getdate(today or nowdate())
	date = getdate(review_date)
	if date < today:
		return OVERDUE
	if date <= getdate(add_days(today, cint(get_settings().review_reminder_days))):
		return DUE
	return CURRENT


# --- In force --------------------------------------------------------------------------------------


def is_in_force(doctype, name):
	"""Whether a document is approved and not past its review date.

	Later documents (JHA, Work Permit) use this to refuse an expired SOP.
	"""
	field = review_date_field(doctype)
	fields = ["workflow_state"] + ([field] if field else [])
	row = frappe.db.get_value(doctype, name, fields, as_dict=True)
	if not row or row.workflow_state != get_approved_state():
		return False
	if field and row.get(field) and getdate(row.get(field)) < getdate(nowdate()):
		return False
	return True


def in_force_conditions(doctype):
	"""Conditions for frappe.get_all that keep only the documents in force, for choosing in a link.

	Use as `frappe.get_all(doctype, **in_force_conditions(doctype))`. A document with no review date
	has no schedule and is in force while it is approved.
	"""
	conditions = {"filters": {"workflow_state": get_approved_state()}}
	field = review_date_field(doctype)
	if field:
		conditions["or_filters"] = [[field, "is", "not set"], [field, ">=", nowdate()]]
	return conditions


def in_force_names(doctype, **filters):
	"""The names of the documents in force, optionally narrowed by more filters."""
	field = review_date_field(doctype)
	rows = frappe.get_all(
		doctype,
		filters={"workflow_state": get_approved_state(), **filters},
		fields=["name"] + ([field] if field else []),
	)
	today = getdate(nowdate())
	return [r.name for r in rows if not field or not r.get(field) or getdate(r.get(field)) >= today]


# --- The daily job ---------------------------------------------------------------------------------


def run_daily():
	"""Update the review status of every approved document and send the reminders that are due."""
	for doctype in review_doctypes():
		if frappe.db.exists("DocType", doctype):
			update_review_statuses(doctype)


def update_review_statuses(doctype, today=None):
	"""Set the status of each approved document of a type, and remind where it is due. Returns a summary."""
	field = review_date_field(doctype)
	if not field:
		return {}

	title_field = frappe.get_meta(doctype).title_field
	fields = ["name", "branch", "document_number", "review_status", field, "name_of_work"]
	if title_field and title_field not in fields:
		fields.append(title_field)

	summary = {CURRENT: 0, DUE: 0, OVERDUE: 0, "": 0}
	for doc in frappe.get_all(doctype, filters={"workflow_state": get_approved_state()}, fields=fields):
		status = review_status_for(doc.get(field), today)
		summary[status] += 1

		if (doc.review_status or "") != status:
			frappe.db.set_value(doctype, doc.name, "review_status", status, update_modified=False)

		if status in (DUE, OVERDUE):
			remind(doctype, doc, field, status, title_field)

	return summary


def remind(doctype, doc, field, status, title_field=None):
	"""Give the people responsible a task and a notice for this stage of this document. Once only."""
	title = (doc.get(title_field) if title_field else None) or doc.get("name_of_work") or ""
	date = formatdate(doc.get(field))
	number = doc.document_number or doc.name

	if status == DUE:
		text = _(
			"{0} {1} {2}is due for review by {3}. Review it, then start a revision (trigger: Scheduled Review) to approve it again."
		)
	else:
		text = _(
			"{0} {1} {2}was due for review on {3} and is now overdue. Review it and approve it again by starting a revision."
		)
	text = text.format(_(doctype), number, f"({title}) " if title else "", date)

	for user in reminder_recipients(doc.branch):
		if frappe.db.exists(
			"ToDo",
			{
				"reference_type": doctype,
				"reference_name": doc.name,
				"allocated_to": user,
				"description": text,
			},
		):
			continue

		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"reference_type": doctype,
				"reference_name": doc.name,
				"description": text,
				"priority": "High" if status == OVERDUE else "Medium",
				"status": "Open",
				"date": doc.get(field),
				"assigned_by": "Administrator",
			}
		).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"type": "Alert",
				"subject": text,
				"for_user": user,
				"from_user": "Administrator",
				"document_type": doctype,
				"document_name": doc.name,
			}
		).insert(ignore_permissions=True)


def reminder_recipients(branch):
	"""The Branch HSE Head users of a branch. When there is none, the HSE Head users, so no reminder is lost."""
	heads = _enabled_users_with_role(REMINDER_ROLE)
	if heads:
		of_branch = frappe.get_all(
			"User Permission",
			filters={"allow": "Branch", "for_value": branch, "user": ("in", heads)},
			pluck="user",
		)
		if of_branch:
			return sorted(set(of_branch))
	return sorted(_enabled_users_with_role(FALLBACK_ROLE))


def _enabled_users_with_role(role):
	users = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if not users:
		return []
	return frappe.get_all(
		"User", filters={"name": ("in", users), "enabled": 1, "user_type": "System User"}, pluck="name"
	)
