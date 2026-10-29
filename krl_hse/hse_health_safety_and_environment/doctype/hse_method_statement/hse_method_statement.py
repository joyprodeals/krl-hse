import frappe
from frappe import _
from frappe.utils import getdate

from krl_hse.utils.controlled_document import ControlledDocument

# Tables whose rows name one of the works of this Method Statement.
WORK_TABLES = (
	("operations", "Sequence of Operations"),
	("equipment", "Equipment"),
	("manpower", "Manpower"),
)

# Type of Activity written on the basic PPE rows, as on KRL's Method Statement format.
BASIC_ACTIVITY = "Basic"


class HSEMethodStatement(ControlledDocument):
	"""Method Statement, KRL/HSE/MS/01 (BRD 6.1.1).

	One Work Order can have any number of them. The project, management and area details are
	copied from the Work Order and the Workplace Areas when the document is made, so an approved
	document does not change when the Work Order later does.
	"""

	def before_validate(self):
		if self.is_new():
			self.fill_from_work_order()
			self.fill_basic_ppe()
			self.fill_emergency_numbers()

	def validate_content(self):
		self.check_dates()
		self.clean_works()
		self.check_work_references()
		self.check_areas()

	# --- New documents ---------------------------------------------------------------------------

	def fill_from_work_order(self):
		"""Copy what the Work Order already knows. Only fills what is still empty."""
		if not self.work_order:
			return

		details = get_work_order_details(self.work_order, check_permission=False)
		for fieldname in ("name_of_work", "client_name", "location", "work_start_date", "work_end_date"):
			if not self.get(fieldname) and details.get(fieldname):
				self.set(fieldname, details[fieldname])

		if not self.management:
			for contact in details["management"]:
				self.append("management", contact)

	def fill_basic_ppe(self):
		if self.ppe:
			return
		for item in get_new_document_defaults()["basic_ppe"]:
			self.append("ppe", item)

	def fill_emergency_numbers(self):
		if self.emergency_numbers:
			return
		for item in get_new_document_defaults()["emergency_numbers"]:
			self.append("emergency_numbers", item)

	# --- Checks ----------------------------------------------------------------------------------

	def check_dates(self):
		if (
			self.work_start_date
			and self.work_end_date
			and getdate(self.work_end_date) < getdate(self.work_start_date)
		):
			frappe.throw(_("Work End Date cannot be before Work Start Date."))

	def clean_works(self):
		seen = set()
		for row in self.works:
			row.work_name = (row.work_name or "").strip()
			if not row.work_name:
				frappe.throw(_("Row {0} of Works: give the work a name.").format(row.idx))
			key = row.work_name.lower()
			if key in seen:
				frappe.throw(
					_("Row {0} of Works: {1} is listed more than once.").format(
						row.idx, frappe.bold(row.work_name)
					)
				)
			seen.add(key)

	def allowed_works(self):
		"""The works of this document, then the common work names (General, Administration, ...)."""
		own = [row.work_name for row in self.works]
		common = frappe.get_all("HSE Common Work", pluck="name", order_by="name")
		return own + [name for name in common if name not in own]

	def check_work_references(self):
		allowed = set(self.allowed_works())
		for fieldname, label in WORK_TABLES:
			for row in self.get(fieldname):
				if row.work and row.work not in allowed:
					frappe.throw(
						_(
							"Row {0} of {1}: {2} is not one of the works. Add it under Works first, or choose from: {3}."
						).format(
							row.idx, label, frappe.bold(row.work), ", ".join(sorted(allowed)) or _("none")
						)
					)

	def check_areas(self):
		seen = set()
		for row in self.areas:
			if row.area in seen:
				frappe.throw(
					_("Row {0} of Areas: {1} is listed more than once.").format(
						row.idx, frappe.bold(row.area)
					)
				)
			seen.add(row.area)

			area = get_area_details(row.area, check_permission=False)
			if area["branch"] != self.branch:
				frappe.throw(
					_(
						"Row {0} of Areas: {1} belongs to branch {2}, but this document is for branch {3}."
					).format(
						row.idx, frappe.bold(row.area), frappe.bold(area["branch"]), frappe.bold(self.branch)
					)
				)
			if area["disabled"]:
				frappe.throw(_("Row {0} of Areas: {1} is disabled.").format(row.idx, frappe.bold(row.area)))
			if area["work_order"] and area["work_order"] != self.work_order:
				frappe.throw(
					_("Row {0} of Areas: {1} belongs to work {2}, not to work {3}.").format(
						row.idx,
						frappe.bold(row.area),
						frappe.bold(area["work_order"]),
						frappe.bold(self.work_order),
					)
				)

			# Fill the leader from the area unless someone has typed one in.
			if not row.leader_name:
				row.leader_name = area["leader_name"]
				row.leader_designation = row.leader_designation or area["leader_designation"]
				row.leader_category = row.leader_category or area["leader_category"]
			if not row.details:
				row.details = area["details"]

	def review_problems(self):
		problems = []
		if not self.works:
			problems.append(_("Add at least one work under Project Work Details."))
		for row in self.works:
			if not any(op.work == row.work_name for op in self.operations):
				problems.append(
					_("Work {0} has no sequence of operations. Give the detailed steps.").format(
						frappe.bold(row.work_name)
					)
				)
		return problems


# --- Called from the form and from the code above ---------------------------------------------------


def get_work_order_details(work_order, check_permission=True):
	"""What a Method Statement copies from its Work Order."""
	if check_permission:
		frappe.has_permission("HSE Work Order", "read", doc=work_order, throw=True)

	order = frappe.get_doc("HSE Work Order", work_order)
	return {
		"branch": order.branch,
		"name_of_work": order.work_title,
		"client_name": order.client_name,
		"location": ", ".join(
			part.strip() for part in (order.plant_name, order.plant_address) if part and part.strip()
		),
		"work_start_date": order.start_date,
		"work_end_date": order.completion_date,
		"management": [
			{
				"contact_role": row.contact_role,
				"party": row.party,
				"employee": row.employee,
				"contact_name": row.contact_name,
				"designation": row.designation,
				"phone": row.phone,
				"email": row.email,
			}
			for row in order.contacts
		],
		"services": [row.description for row in order.service_lines if row.description],
	}


def get_area_details(area, check_permission=True):
	"""The area's branch and work, its current team leader and its location details."""
	if check_permission:
		frappe.has_permission("HSE Workplace Area", "read", doc=area, throw=True)

	doc = frappe.get_doc("HSE Workplace Area", area)
	leader_roles = set(frappe.get_all("HSE Area Team Role", filters={"is_leader": 1}, pluck="name"))
	leader = next((row for row in doc.team if row.team_role in leader_roles and not row.to_date), None)
	return {
		"area": doc.name,
		"branch": doc.branch,
		"work_order": doc.work_order,
		"disabled": doc.disabled,
		"leader_name": leader.member_name if leader else "",
		"leader_designation": leader.designation if leader else "",
		"leader_category": leader.category if leader else "",
		"details": doc.location_details or "",
	}


def get_new_document_defaults():
	"""Rows every new Method Statement starts with: the basic PPE and the emergency numbers."""
	basic = frappe.get_all(
		"HSE PPE Item",
		filters={"is_basic": 1},
		fields=["name", "standard"],
		order_by="sort_order asc, name asc",
	)
	contacts = frappe.get_all("HSE Emergency Contact Type", pluck="name", order_by="sort_order asc, name asc")
	return {
		"basic_ppe": [
			{"activity": BASIC_ACTIVITY, "ppe": row.name, "standard": row.standard} for row in basic
		],
		"emergency_numbers": [{"contact_type": name} for name in contacts],
	}


@frappe.whitelist()
def work_order_details(work_order):
	return get_work_order_details(work_order)


@frappe.whitelist()
def area_details(area):
	return get_area_details(area)


@frappe.whitelist()
def work_areas(work_order):
	"""The areas that belong to a Work Order, with their leaders, for the Add Areas button."""
	frappe.has_permission("HSE Work Order", "read", doc=work_order, throw=True)
	names = frappe.get_all(
		"HSE Workplace Area",
		filters={"work_order": work_order, "disabled": 0},
		pluck="name",
		order_by="area_name",
	)
	return [get_area_details(name, check_permission=False) for name in names]


@frappe.whitelist()
def new_document_defaults():
	return get_new_document_defaults()
