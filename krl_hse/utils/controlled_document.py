"""Base class for the controlled planning documents: Method Statement, HIRA, SOP and JHA.

These four share one control pattern (BRD 6.1): a document stays in Draft until it is sent for
review, an approver approves it or sends it back with recommendations, and once approved it is in
force. It cannot then be edited. A change is made as a new revision, which is not in force until it
is approved, and the earlier revision stays in force until then.

How that is kept here:

  * A revision is a record of its own. All revisions share one `document_number`. The first record
    is named by that number; a later one is named `<number>-R<revision>`. Each keeps its own
    approvals, so the full history of who approved what stays on the record.
  * An approved record, and a superseded one, cannot be changed or deleted.
  * When a revision is approved, the revision it replaces moves to the superseded state.
  * Every change of approval state is written to the Sign-offs table with the user and the time.
    "Prepared by" and "Approved by" on the printed format are read from it.

The names of the approved and superseded states are settings (HSE Settings), not code. The
approval levels are the workflow of each document type, which KRL can edit in the Desk.
"""

import frappe
from frappe import _
from frappe.model.workflow import get_workflow_name
from frappe.utils import cint, get_fullname, now_datetime, nowdate

from krl_hse.utils.hse_document import HSEDocument


def get_settings():
	return frappe.get_cached_doc("HSE Settings")


def get_approved_state():
	return get_settings().approved_state or "Approved"


def get_superseded_state():
	return get_settings().superseded_state or "Superseded"


def get_controlled_doctypes():
	return frappe.get_hooks("hse_controlled_doctypes")


def get_workflow(doctype):
	name = get_workflow_name(doctype)
	return frappe.get_cached_doc("Workflow", name) if name else None


class ControlledDocument(HSEDocument):
	"""A numbered, branch-tagged, revisioned and approved document. See the module note."""

	number_job_field = "work_order"

	# --- Numbering ----------------------------------------------------------------------------

	def autoname(self):
		if self.previous_revision:
			base = frappe.db.get_value(self.doctype, self.previous_revision, "document_number")
			self.document_number = base
			self.name = f"{base}-R{cint(self.revision_number)}"
		else:
			super().autoname()
			self.document_number = self.name

	# --- Saving -------------------------------------------------------------------------------

	def validate(self):
		self.check_not_frozen()
		self.check_work_order()
		self.check_revision_details()
		self.validate_content()
		self.check_ready_for_review()
		self.stamp_issue_dates()
		self.record_sign_off()

	def validate_content(self):
		"""Document-specific checks. Override in the document type."""

	def review_problems(self):
		"""What is still missing before this can be sent for review. Override in the document type."""
		return []

	def check_not_frozen(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if before and before.workflow_state in (get_approved_state(), get_superseded_state()):
			frappe.throw(
				_(
					"{0} is {1} and cannot be changed. To change it, start a new revision from the {1} one."
				).format(frappe.bold(self.name), before.workflow_state.lower()),
				title=_("Document is in force"),
			)

	def check_work_order(self):
		if not self.work_order:
			return

		work_branch, status = frappe.db.get_value("HSE Work Order", self.work_order, ["branch", "status"])
		if work_branch != self.branch:
			frappe.throw(
				_("Work {0} belongs to branch {1}, but this document is for branch {2}.").format(
					frappe.bold(self.work_order), frappe.bold(work_branch), frappe.bold(self.branch)
				)
			)

		if self.is_new() and status in ("Completed", "Cancelled"):
			frappe.throw(
				_("Work {0} is {1}, so no new document can be made for it.").format(
					frappe.bold(self.work_order), status.lower()
				)
			)

	def check_revision_details(self):
		"""A revision must say what triggered it and what changed."""
		if cint(self.revision_number) < 1 or not self.is_new():
			return
		if not self.revision_trigger or not (self.revision_remark or "").strip():
			frappe.throw(_("Say what triggered this revision and what changed."))

	def check_ready_for_review(self):
		"""Refuse to leave Draft or Sent Back while the document is incomplete."""
		before = self.get_doc_before_save()
		if not before or before.workflow_state == self.workflow_state:
			return

		workflow = get_workflow(self.doctype)
		start_states = {get_settings().sent_back_state}
		if workflow and workflow.states:
			start_states.add(workflow.states[0].state)

		if before.workflow_state in start_states and self.workflow_state not in start_states:
			problems = self.review_problems()
			if problems:
				frappe.throw(
					"<br>".join(problems),
					title=_("Not ready to send for review"),
				)

	def stamp_issue_dates(self):
		before = self.get_doc_before_save()
		approved = get_approved_state()
		if self.workflow_state != approved or (before and before.workflow_state == approved):
			return

		today = nowdate()
		if not self.first_issue_date:
			self.first_issue_date = today
		if cint(self.revision_number) > 0:
			self.revision_date = today

	def record_sign_off(self):
		"""Write each change of approval state to the Sign-offs table."""
		workflow = get_workflow(self.doctype)

		if self.is_new():
			first_state = workflow.states[0].state if workflow and workflow.states else ""
			remarks = (
				_("Revision {0} of {1}").format(self.revision_number, self.previous_revision)
				if self.previous_revision
				else None
			)
			self.add_sign_off(_("Prepared"), "", first_state, remarks)
			return

		before = self.get_doc_before_save()
		if not before or before.workflow_state == self.workflow_state:
			return

		action = next(
			(
				t.action
				for t in (workflow.transitions if workflow else [])
				if t.state == before.workflow_state and t.next_state == self.workflow_state
			),
			self.workflow_state,
		)
		remarks = None
		if self.workflow_state == get_settings().sent_back_state:
			remarks = self.get("recommendations")
		self.add_sign_off(action, before.workflow_state, self.workflow_state, remarks)

	def add_sign_off(self, action, from_state, to_state, remarks=None):
		self.append(
			"sign_offs",
			{
				"action": action,
				"from_state": from_state,
				"to_state": to_state,
				"user": frappe.session.user,
				"full_name": get_fullname(frappe.session.user),
				"signed_on": now_datetime(),
				"remarks": remarks,
			},
		)

	def on_update(self):
		if (
			self.previous_revision
			and self.workflow_state == get_approved_state()
			and self.has_value_changed("workflow_state")
		):
			self.supersede_previous_revision()

	def supersede_previous_revision(self):
		frappe.db.set_value(
			self.doctype,
			self.previous_revision,
			"workflow_state",
			get_superseded_state(),
			update_modified=True,
		)
		frappe.get_doc(self.doctype, self.previous_revision).add_comment(
			"Info", _("Superseded by revision {0}, {1}.").format(self.revision_number, self.name)
		)

	def on_trash(self):
		if self.workflow_state in (get_approved_state(), get_superseded_state()):
			frappe.throw(
				_("{0} is {1} and cannot be deleted.").format(
					frappe.bold(self.name), self.workflow_state.lower()
				),
				title=_("Document is in force"),
			)


# --- Revisions ------------------------------------------------------------------------------------


def _check_controlled(doctype):
	if doctype not in get_controlled_doctypes():
		frappe.throw(_("{0} is not a controlled document type.").format(frappe.bold(doctype)))


def get_revision_status(doctype, name):
	"""Where a record stands among the revisions of its document number."""
	_check_controlled(doctype)
	number, revision = frappe.db.get_value(doctype, name, ["document_number", "revision_number"])
	rows = frappe.get_all(
		doctype,
		filters={"document_number": number},
		fields=["name", "revision_number", "workflow_state"],
		order_by="revision_number desc",
		limit=1,
	)
	latest = rows[0] if rows else None
	# A later revision the user may not see (a draft, for a viewer) is not mentioned.
	if latest and latest.name != name and not frappe.has_permission(doctype, "read", doc=latest.name):
		latest = None
	if latest is None:
		return {
			"document_number": number,
			"revision_number": cint(revision),
			"is_latest": True,
			"latest": name,
			"latest_state": frappe.db.get_value(doctype, name, "workflow_state"),
		}
	return {
		"document_number": number,
		"revision_number": cint(revision),
		"is_latest": bool(latest and latest.name == name),
		"latest": latest.name if latest else None,
		"latest_state": latest.workflow_state if latest else None,
	}


@frappe.whitelist()
def revision_status(doctype, name):
	"""For the form: where the record stands among its revisions, and whether the user can revise it."""
	frappe.has_permission(doctype, "read", doc=name, throw=True)
	status = get_revision_status(doctype, name)
	status["can_revise"] = bool(
		status["is_latest"]
		and frappe.db.get_value(doctype, name, "workflow_state") == get_approved_state()
		and frappe.has_permission(doctype, "create")
	)
	return status


@frappe.whitelist()
def start_revision(doctype, name, revision_trigger, revision_remark, source_document=None):
	"""Start the next revision of an approved document, as a new Draft.

	The approved revision stays in force until the new one is approved.
	"""
	_check_controlled(doctype)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	frappe.has_permission(doctype, "create", throw=True)

	if doc.workflow_state != get_approved_state():
		frappe.throw(
			_("Only an {0} document can be revised. {1} is {2}.").format(
				get_approved_state().lower(), frappe.bold(name), (doc.workflow_state or "").lower()
			)
		)

	status = get_revision_status(doctype, name)
	if not status["is_latest"]:
		frappe.throw(
			_("{0} already has a later revision, {1}. Revise that one.").format(
				frappe.bold(name), frappe.bold(status["latest"])
			)
		)

	new = frappe.copy_doc(doc)
	new.revision_number = cint(doc.revision_number) + 1
	new.previous_revision = doc.name
	new.revision_trigger = revision_trigger
	new.revision_remark = revision_remark
	new.source_document = source_document
	new.workflow_state = None
	new.revision_date = None
	new.set("sign_offs", [])
	new.insert()
	return new.name
