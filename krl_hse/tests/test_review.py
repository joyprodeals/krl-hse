import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, nowdate

from krl_hse.tests.test_sop import (
	BRANCH_HEAD,
	CREATOR,
	DOCTYPE,
	HO_TEAM,
	REVIEWER,
	SOPTestCase,
)
from krl_hse.tests.utils import (
	act_on,
	hira_line,
	make_hira,
	make_user,
	override_setting,
)
from krl_hse.utils.controlled_document import start_revision
from krl_hse.utils.review import (
	CURRENT,
	DUE,
	OVERDUE,
	in_force_conditions,
	in_force_names,
	is_in_force,
	reminder_recipients,
	review_date_field,
	review_status_for,
	run_daily,
	update_review_statuses,
)

OTHER_HEAD = "test.review_bhse_j@krl-test.example"
HSE_HEAD = "test.review_hse_head@krl-test.example"


class TestReviewStatus(IntegrationTestCase):
	def test_the_status_follows_the_distance_to_the_date(self):
		today = nowdate()
		self.assertEqual(review_status_for(add_days(today, 31), today), CURRENT)
		self.assertEqual(review_status_for(add_days(today, 30), today), DUE)
		self.assertEqual(review_status_for(today, today), DUE)
		self.assertEqual(review_status_for(add_days(today, -1), today), OVERDUE)

	def test_no_date_means_no_status(self):
		self.assertEqual(review_status_for(None), "")

	def test_the_reminder_period_is_a_setting(self):
		today = nowdate()
		self.addCleanup(override_setting("review_reminder_days", 10))
		self.assertEqual(review_status_for(add_days(today, 11), today), CURRENT)
		self.assertEqual(review_status_for(add_days(today, 10), today), DUE)

	def test_the_documents_that_are_reviewed_are_named_in_the_hooks(self):
		self.assertEqual(review_date_field("HSE HIRA"), "next_review_date")
		self.assertEqual(review_date_field("HSE SOP"), "validity_date")
		self.assertIsNone(review_date_field("HSE Method Statement"))

	def test_every_reviewed_type_is_set_up_for_it(self):
		controlled = frappe.get_hooks("hse_controlled_doctypes")
		for doctype in frappe.get_hooks("hse_review_date_fields") or {}:
			field = review_date_field(doctype)
			meta = frappe.get_meta(doctype)
			self.assertIn(doctype, controlled)
			self.assertTrue(meta.has_field(field), (doctype, field))
			self.assertTrue(meta.has_field("review_status"), doctype)

	def test_the_daily_job_is_scheduled(self):
		self.assertIn("krl_hse.utils.review.run_daily", frappe.get_hooks("scheduler_events")["daily"])

	def test_a_scheduled_review_is_a_revision_trigger(self):
		self.assertTrue(frappe.db.exists("HSE Revision Trigger", "Scheduled Review"))


class ReviewTestCase(SOPTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(OTHER_HEAD, ["Branch HSE Head"], branches=["TEST Jharsuguda"])
		make_user(HSE_HEAD, ["HSE Head"])

	def approved_sop(self, days_left=200):
		sop = self.approve(self.new_sop())
		frappe.db.set_value(DOCTYPE, sop.name, "validity_date", add_days(nowdate(), days_left))
		return sop

	def status(self, doctype, name):
		return frappe.db.get_value(doctype, name, "review_status")

	def todos(self, doctype, name, user=None):
		filters = {"reference_type": doctype, "reference_name": name}
		if user:
			filters["allocated_to"] = user
		return frappe.get_all(
			"ToDo", filters=filters, fields=["name", "allocated_to", "status", "description"]
		)

	def notices(self, doctype, name, user):
		return frappe.get_all(
			"Notification Log",
			filters={"document_type": doctype, "document_name": name, "for_user": user},
			pluck="subject",
		)


class TestStatusOfRecords(ReviewTestCase):
	def test_a_draft_has_no_status(self):
		self.assertFalse(self.new_sop().review_status)

	def test_approval_sets_the_status_from_the_validity_date(self):
		self.assertEqual(self.approve(self.new_sop()).review_status, CURRENT)

	def test_a_sop_approved_close_to_its_date_is_due_at_once(self):
		sop = self.new_sop(validity_date=add_days(nowdate(), 5))
		self.assertEqual(self.approve(sop).review_status, DUE)

	def test_a_hira_is_current_after_approval_with_a_review_period(self):
		hira = make_hira("TEST Athagarh", self.ms.name, area=self.area.name)
		act_on(CREATOR, "HSE HIRA", hira.name, "Submit for Review")
		act_on(REVIEWER, "HSE HIRA", hira.name, "Review and Forward")
		act_on(BRANCH_HEAD, "HSE HIRA", hira.name, "Approve")
		frappe.set_user("Administrator")
		approved = frappe.get_doc("HSE HIRA", hira.name)
		self.assertEqual(str(approved.next_review_date), str(add_months(nowdate(), 6)))
		self.assertEqual(approved.review_status, CURRENT)

	def test_the_daily_job_moves_the_status_as_the_date_nears_and_passes(self):
		sop = self.approved_sop(days_left=200)
		update_review_statuses(DOCTYPE)
		self.assertEqual(self.status(DOCTYPE, sop.name), CURRENT)

		frappe.db.set_value(DOCTYPE, sop.name, "validity_date", add_days(nowdate(), 12))
		update_review_statuses(DOCTYPE)
		self.assertEqual(self.status(DOCTYPE, sop.name), DUE)

		frappe.db.set_value(DOCTYPE, sop.name, "validity_date", add_days(nowdate(), -2))
		update_review_statuses(DOCTYPE)
		self.assertEqual(self.status(DOCTYPE, sop.name), OVERDUE)

	def test_the_daily_job_does_not_touch_drafts_or_change_the_modified_time(self):
		draft = self.new_sop(validity_date=add_days(nowdate(), 3))
		sop = self.approved_sop(days_left=3)
		before = frappe.db.get_value(DOCTYPE, sop.name, "modified")
		update_review_statuses(DOCTYPE)
		self.assertFalse(self.status(DOCTYPE, draft.name))
		self.assertEqual(self.status(DOCTYPE, sop.name), DUE)
		self.assertEqual(frappe.db.get_value(DOCTYPE, sop.name, "modified"), before)

	def test_the_summary_counts_each_status(self):
		self.approved_sop(days_left=3)
		summary = update_review_statuses(DOCTYPE)
		self.assertGreaterEqual(summary[DUE], 1)

	def test_a_superseded_revision_has_no_status(self):
		approved = self.approved_sop()
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, approved.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		revision = frappe.get_doc(DOCTYPE, name)
		self.assertFalse(revision.review_status)
		self.assertFalse(revision.validity_date)
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		revision = self.approve_revision(revision)
		self.assertEqual(self.status(DOCTYPE, approved.name), "")
		self.assertEqual(revision.review_status, CURRENT)


class TestInForce(ReviewTestCase):
	def test_an_approved_sop_within_its_validity_is_in_force(self):
		sop = self.approved_sop()
		self.assertTrue(is_in_force(DOCTYPE, sop.name))
		self.assertIn(sop.name, in_force_names(DOCTYPE))

	def test_an_expired_sop_is_not_in_force(self):
		sop = self.approved_sop(days_left=-1)
		self.assertFalse(is_in_force(DOCTYPE, sop.name))
		self.assertNotIn(sop.name, in_force_names(DOCTYPE))

	def test_the_last_day_of_validity_still_counts(self):
		sop = self.approved_sop(days_left=0)
		self.assertTrue(is_in_force(DOCTYPE, sop.name))

	def test_a_draft_is_not_in_force(self):
		sop = self.new_sop()
		self.assertFalse(is_in_force(DOCTYPE, sop.name))

	def test_a_superseded_sop_is_not_in_force(self):
		approved = self.approved_sop()
		frappe.set_user(CREATOR)
		name = start_revision(DOCTYPE, approved.name, "Scheduled Review", "TEST: no change")
		frappe.set_user("Administrator")
		revision = frappe.get_doc(DOCTYPE, name)
		revision.validity_date = add_months(nowdate(), 12)
		revision.save(ignore_permissions=True)
		self.approve_revision(revision)
		self.assertFalse(is_in_force(DOCTYPE, approved.name))
		self.assertTrue(is_in_force(DOCTYPE, name))

	def test_it_does_not_wait_for_the_daily_job(self):
		sop = self.approved_sop(days_left=-1)
		self.assertNotEqual(self.status(DOCTYPE, sop.name), OVERDUE)
		self.assertFalse(is_in_force(DOCTYPE, sop.name))

	def test_the_link_conditions_keep_only_the_ones_in_force(self):
		good = self.approved_sop()
		expired = self.approved_sop(days_left=-5)
		names = frappe.get_all(DOCTYPE, pluck="name", **in_force_conditions(DOCTYPE))
		self.assertIn(good.name, names)
		self.assertNotIn(expired.name, names)

	def test_a_hira_without_a_review_date_is_in_force_while_approved(self):
		hira = make_hira("TEST Athagarh", self.ms.name, area=self.area.name)
		frappe.db.set_value("HSE HIRA", hira.name, {"workflow_state": "Approved", "next_review_date": None})
		self.assertTrue(is_in_force("HSE HIRA", hira.name))
		self.assertIn(hira.name, frappe.get_all("HSE HIRA", pluck="name", **in_force_conditions("HSE HIRA")))


class TestReminders(ReviewTestCase):
	def test_the_branch_hse_head_of_the_branch_is_reminded(self):
		sop = self.approved_sop(days_left=10)
		update_review_statuses(DOCTYPE)
		todos = self.todos(DOCTYPE, sop.name, REVIEWER)
		self.assertEqual(len(todos), 1)
		self.assertIn("due for review", todos[0].description)
		self.assertIn(sop.document_number, todos[0].description)
		self.assertEqual(len(self.notices(DOCTYPE, sop.name, REVIEWER)), 1)

	def test_the_head_of_another_branch_is_not(self):
		sop = self.approved_sop(days_left=10)
		update_review_statuses(DOCTYPE)
		self.assertEqual(self.todos(DOCTYPE, sop.name, OTHER_HEAD), [])

	def test_nobody_is_reminded_while_the_document_is_current(self):
		sop = self.approved_sop(days_left=200)
		update_review_statuses(DOCTYPE)
		self.assertEqual(self.todos(DOCTYPE, sop.name), [])

	def test_a_reminder_is_sent_once_for_each_stage(self):
		sop = self.approved_sop(days_left=10)
		update_review_statuses(DOCTYPE)
		update_review_statuses(DOCTYPE)
		self.assertEqual(len(self.todos(DOCTYPE, sop.name, REVIEWER)), 1)

	def test_closing_the_task_does_not_bring_it_back(self):
		sop = self.approved_sop(days_left=10)
		update_review_statuses(DOCTYPE)
		for todo in self.todos(DOCTYPE, sop.name, REVIEWER):
			frappe.db.set_value("ToDo", todo.name, "status", "Closed")
		update_review_statuses(DOCTYPE)
		self.assertEqual(len(self.todos(DOCTYPE, sop.name, REVIEWER)), 1)

	def test_overdue_is_a_new_reminder(self):
		sop = self.approved_sop(days_left=10)
		update_review_statuses(DOCTYPE)
		frappe.db.set_value(DOCTYPE, sop.name, "validity_date", add_days(nowdate(), -1))
		update_review_statuses(DOCTYPE)
		todos = self.todos(DOCTYPE, sop.name, REVIEWER)
		self.assertEqual(len(todos), 2)
		self.assertTrue(any("overdue" in t.description for t in todos))

	def test_the_daily_run_reminds_for_a_hira_too(self):
		hira = make_hira("TEST Athagarh", self.ms.name, area=self.area.name)
		frappe.db.set_value(
			"HSE HIRA",
			hira.name,
			{"workflow_state": "Approved", "next_review_date": add_days(nowdate(), 5)},
		)
		run_daily()
		self.assertEqual(self.status("HSE HIRA", hira.name), DUE)
		self.assertEqual(len(self.todos("HSE HIRA", hira.name, REVIEWER)), 1)

	def test_a_branch_without_a_branch_hse_head_falls_back_to_the_hse_head(self):
		recipients = reminder_recipients("TEST Some Branch Without One")
		self.assertIn(HSE_HEAD, recipients)
		self.assertNotIn(REVIEWER, recipients)
		self.assertNotIn(OTHER_HEAD, recipients)

	def test_the_branch_hse_head_is_chosen_by_the_branch(self):
		self.assertIn(REVIEWER, reminder_recipients("TEST Athagarh"))
		self.assertNotIn(OTHER_HEAD, reminder_recipients("TEST Athagarh"))
		self.assertEqual(reminder_recipients("TEST Jharsuguda"), [OTHER_HEAD])

	def test_a_disabled_head_is_not_reminded(self):
		frappe.db.set_value("User", OTHER_HEAD, "enabled", 0)
		self.addCleanup(frappe.db.set_value, "User", OTHER_HEAD, "enabled", 1)
		self.assertNotIn(OTHER_HEAD, reminder_recipients("TEST Jharsuguda"))
