"""Demo data for the Phase 1 walk-through. NOT part of the live install.

Nothing here runs on install or migrate. It is run by hand on a demo or test site:

	bench --site <site> execute krl_hse.demo.seed.load
	bench --site <site> execute krl_hse.demo.seed.clear

Rules it follows:
  * Every record it makes carries a TEST name or a TEST address, so it is easy to find.
  * People have dummy names. Email addresses use the reserved example domain, so nothing
    can reach a real person.
  * It never edits an existing record except to give an existing Branch its HSE Branch Code,
    and it says so before it does.
  * `clear` archives by default (cancels work orders, disables areas and users). It deletes
    only when called with delete=1, which is for KRL-approved clean-up before go-live.

Branches are never created here and no branch name is fixed in this file. The branches already on
the site are given their HSE Branch Code by the person running the load:

	bench --site <site> execute krl_hse.demo.seed.load --kwargs \\
		"{'branches': {'<branch name>': '<code>', ...}, 'head_office': '<branch name>'}"

If every branch already has its code, `load` needs no arguments. The sample people and records refer
to branches by code. J and T carry the two sample jobs. A person or record whose code is not on the
site is skipped, and the load says so.
"""

import json

import frappe

DOMAIN = "krl-demo.example"

# One dummy person per role. (key, role, first name, branch codes, or None for all branches)
USERS = [
	("director", "Director", "TEST Director", None),
	("hse_head", "HSE Head", "TEST HSE Head", None),
	("ho_hse", "HO HSE Team", "TEST HO HSE Member", None),
	("bhse_t", "Branch HSE Head", "TEST Athagarh HSE Head", ["T"]),
	("bhse_j", "Branch HSE Head", "TEST Jharsuguda HSE Head", ["J"]),
	("officer_t", "HSE Officer", "TEST Athagarh HSE Officer", ["T"]),
	("hse_sup_t", "HSE Supervisor", "TEST Athagarh HSE Supervisor", ["T"]),
	("bhead_t", "Branch Head", "TEST Athagarh Branch Head", ["T"]),
	("bhead_j", "Branch Head", "TEST Jharsuguda Branch Head", ["J"]),
	("dept_t", "Branch Department Head", "TEST Athagarh Maintenance Head", ["T"]),
	("site_sup_t", "Site Supervisor", "TEST Athagarh Site Supervisor", ["T"]),
	("store_t", "Store In-charge", "TEST Athagarh Store In-charge", ["T"]),
]

WORK_ORDERS = [
	{
		"branch": "J",
		"job_code": "TEST-SLAG",
		"work_title": "TEST Slag handling at the client plant",
		"client_name": "TEST Client Steel Limited",
		"plant_name": "TEST Client Plant, Sambalpur",
		"po_number": "TEST-4500188553",
		"po_date": "2024-06-01",
		"start_date": "2024-07-01",
		"completion_date": "2025-06-30",
		"client_safety_terms": "<p>TEST: workers must be above 18 years. Working height as stated per service.</p>",
		"service_lines": [
			{
				"service_code": "TEST-S1",
				"description": "TEST Handling of furnace slag",
				"qty": 340000,
				"uom": "Tonne",  # dropped by _ensure_work_orders if this UOM does not exist on the site
				"working_height_m": 0,
			},
			{
				"service_code": "TEST-S2",
				"description": "TEST Cleaning of slag pit",
				"qty": 1,
				"working_height_m": 3,
			},
		],
		"contacts": [
			{"contact_role": "Branch Head", "contact_name": "TEST Jharsuguda Branch Head"},
			{"contact_role": "HSE Head", "contact_name": "TEST Jharsuguda HSE Head"},
			{"contact_role": "Client Representative", "contact_name": "TEST Client Representative"},
			{"contact_role": "Client HSE Representative", "contact_name": "TEST Client HSE Officer"},
		],
	},
	{
		"branch": "T",
		"job_code": "TEST-ATH",
		"work_title": "TEST Material handling at Athagarh",
		"client_name": "TEST Client Metals Limited",
		"plant_name": "TEST Client Plant, Athagarh",
		"po_number": "TEST-ATH-001",
		"po_date": "2026-04-01",
		"start_date": "2026-04-15",
		"completion_date": "2027-03-31",
		"service_lines": [{"service_code": "TEST-A1", "description": "TEST Loading and unloading", "qty": 1}],
		"contacts": [{"contact_role": "Branch Head", "contact_name": "TEST Athagarh Branch Head"}],
	},
]

AREAS = [
	# (branch code, job code of its work or None, area name, division type, details, leader, members)
	(
		"T",
		"TEST-ATH",
		"TEST Loading Yard",
		"Location",
		"TEST: open yard near gate 1",
		"TEST Yard Lead",
		["TEST Yard Member A", "TEST Yard Member B"],
	),
	(
		"T",
		"TEST-ATH",
		"TEST Workshop",
		"Work",
		"TEST: maintenance workshop",
		"TEST Workshop Lead",
		["TEST Workshop Member A", "TEST Workshop Member B"],
	),
	(
		"J",
		"TEST-SLAG",
		"TEST Slag Pit",
		"Location",
		"TEST: pit side",
		"TEST Pit Lead",
		["TEST Pit Member A", "TEST Pit Member B"],
	),
]

METHOD_STATEMENTS = [
	# One Method Statement left in Draft for each sample work, ready to be sent for review.
	{
		"branch": "T",
		"job_code": "TEST-ATH",
		"areas": ["TEST Loading Yard", "TEST Workshop"],
		"works": [
			{"work_name": "TEST Loading", "description": "TEST: loading trucks in the yard"},
			{"work_name": "TEST Workshop servicing", "description": "TEST: servicing of loaders"},
		],
		"operations": [
			("TEST Loading", "TEST: inspect the loader and the yard before the shift"),
			("TEST Loading", "TEST: position the truck at the marked bay"),
			("TEST Loading", "TEST: load, check the load and release the truck"),
			("TEST Workshop servicing", "TEST: park the loader, switch off and isolate"),
			("TEST Workshop servicing", "TEST: service as per the job card"),
		],
		"equipment": [
			("TEST Loading", "TEST Wheel loader", 2),
			("General", "TEST Crew bus", 1),
			("Maint-Fleet", "TEST Service van", 1),
		],
		"manpower": [
			("TEST Loading", "TEST Loader Operator", "Worker", 6),
			("TEST Workshop servicing", "TEST Fitter", "Worker", 3),
			("Administration", "TEST Store Keeper", "SL", 1),
		],
		"ppe": [
			("TEST Workshop servicing", "Goggles", "TEST: welding goggles"),
		],
		"sops": [("TEST Loading", "TEST-SOP-LOAD-01"), ("TEST Workshop servicing", "TEST-SOP-SERV-01")],
		"hazards": [
			("TEST Loading", "TEST: contact with moving equipment, slip and trip", "TEST-HIRA-LOAD-01"),
			("TEST Workshop servicing", "TEST: hot surfaces, stored energy", ""),
		],
		"emergency_procedures": [("Fire", "TEST-ERP-FIRE-01"), ("Medical", "TEST-ERP-MED-01")],
		"emergency_numbers": {
			"Fire Department": ("TEST-101", "TEST plant fire station"),
			"Ambulance / Hospital": ("TEST-108", "TEST plant hospital"),
		},
	},
	{
		"branch": "J",
		"job_code": "TEST-SLAG",
		"areas": ["TEST Slag Pit"],
		"works": [{"work_name": "TEST Slag handling", "description": "TEST: handling of furnace slag"}],
		"operations": [
			("TEST Slag handling", "TEST: clear the pit side and place barricades"),
			("TEST Slag handling", "TEST: load slag into the dumper under supervision"),
		],
		"equipment": [("TEST Slag handling", "TEST Excavator", 1)],
		"manpower": [("TEST Slag handling", "TEST Loader Operator", "Worker", 4)],
		"ppe": [],
		"sops": [("TEST Slag handling", "TEST-SOP-SLAG-01")],
		"hazards": [("TEST Slag handling", "TEST: contact with hot metal, fire, dust", "TEST-HIRA-SLAG-01")],
		"emergency_procedures": [("Fire", "TEST-ERP-FIRE-02")],
		"emergency_numbers": {},
	},
]

# One Draft HIRA for the approved Method Statement of each sample work. A line is
# (job, routine, activity category, activity, hazard category, hazard, hazardous event, cause,
#  consequence, impact area, existing safeguard, recommendation, ratings). The ratings are the
# consequence and likelihood before the controls, then after them.
HIRAS = [
	{
		"job_code": "TEST-ATH",
		"area": "TEST Loading Yard",
		"lines": [
			(
				"TEST Loading",
				"Routine",
				"Equipment",
				"TEST: the wheel loader moves in the yard",
				"Physical",
				"TEST: moving vehicle close to people",
				"TEST: the loader hits a person",
				"TEST: poor visibility, nobody guiding the loader",
				"TEST: serious injury or death",
				"People",
				"TEST: reverse alarm and horn",
				"TEST: appoint a banksman for every reversing move",
				("C4 Major", "Possible", "C4 Major", "Rare"),
			),
			(
				"TEST Loading",
				"Routine",
				"Physical Conditions",
				"TEST: walking in the yard during loading",
				"Physical",
				"TEST: uneven ground and loose material",
				"TEST: a person slips or trips",
				"TEST: poor housekeeping",
				"TEST: sprain or fracture",
				"People",
				"TEST: marked walkways",
				"",
				("C2 Minor", "Possible", "C1 Insignificant", "Rare"),
			),
			(
				"TEST Workshop servicing",
				"Non-Routine",
				"Substances",
				"TEST: draining oil during servicing",
				"Chemical",
				"TEST: used oil",
				"TEST: oil spills on the floor and reaches the drain",
				"TEST: no drip tray",
				"TEST: soil and water contamination",
				"Environment",
				"TEST: absorbent material kept in the workshop",
				"TEST: provide drip trays at every service bay",
				("C2 Minor", "Unlikely", "C1 Insignificant", "Unlikely"),
			),
		],
		"controls": [
			(1, "Existing", "TEST: reverse alarm and horn on every loader", "Engineering Control"),
			(1, "Existing", "TEST: loader operators trained and authorised", "Administrative Control"),
			(2, "Existing", "TEST: walkways marked with paint and signs", "Administrative Control"),
		],
	},
	{
		"job_code": "TEST-SLAG",
		"area": "TEST Slag Pit",
		"lines": [
			(
				"TEST Slag handling",
				"Routine",
				"Materials",
				"TEST: loading hot slag into the dumper",
				"Physical",
				"TEST: hot metal and heat",
				"TEST: splash of hot slag on a worker",
				"TEST: slag not cooled, people too close",
				"TEST: severe burns",
				"People",
				"TEST: barricade around the pit",
				"TEST: allow loading only after the cooling time is over",
				("C5 Catastrophic", "Possible", "C4 Major", "Rare"),
			),
			(
				"TEST Slag handling",
				"Routine",
				"Physical Conditions",
				"TEST: working at the pit side",
				"Biological",
				"TEST: dust and fumes",
				"TEST: breathing in dust",
				"TEST: no dust suppression",
				"TEST: lung irritation",
				"People",
				"",
				"TEST: water sprinkling during loading",
				("C2 Minor", "Very Likely", "C1 Insignificant", "Unlikely"),
			),
		],
		"controls": [
			(1, "Existing", "TEST: barricade and warning signs around the pit", "Isolation"),
			(1, "Existing", "TEST: heat-resistant suit and face shield", "PPE"),
			(2, "Existing", "TEST: dust mask issued to every worker", "PPE"),
		],
	},
]

# One Draft SOP for the approved Method Statement of each sample work. A hazard is (hazard, mitigation,
# HIRA line), the line being filled only when the work has a HIRA. A step is (activity, requirements,
# hazard and impact, who, how, remarks). The distribution is (recipient, user key, copies).
SOPS = [
	{
		"job_code": "TEST-SLAG",
		"title": "TEST Hot slag loading",
		"work": "TEST Slag handling",
		"area": "TEST Slag Pit",
		"purpose": "TEST: load hot slag into the dumper without injury or fire.",
		"scope": "TEST: all slag loading at the slag pit.",
		"applicable_to": "TEST: slag pit crew, supervisors and dumper drivers",
		"definitions": "TEST: hot slag is slag that has not finished its cooling time.",
		"annexure": "TEST: cooling-time chart and pit layout drawing",
		"hazards": [
			("TEST: splash of hot slag on a worker", "TEST: load only after the cooling time is over", "L1"),
			(
				"TEST: splash of hot slag on a worker",
				"TEST: heat-resistant suit and face shield for everyone at the pit",
				"L1",
			),
			("TEST: breathing in dust", "TEST: water sprinkling during loading", "L2"),
		],
		"rules": [
			("Do", "TEST: confirm the cooling time with the shift in-charge before loading"),
			("Do", "TEST: stay behind the barricade until the excavator stops"),
			("Don't", "TEST: do not stand under the excavator bucket"),
			("Don't", "TEST: do not load into a damaged dumper"),
		],
		"steps": [
			(
				"TEST: clear the pit side and place barricades",
				"TEST: barricades and signs available",
				"TEST: people too close to the pit",
				"TEST Supervisor",
				"TEST: barricade the pit side, post a banksman",
				"",
			),
			(
				"TEST: check the cooling time",
				"TEST: cooling-time chart",
				"TEST: splash of hot slag",
				"TEST Supervisor",
				"TEST: read the chart, record the time in the log",
				"TEST: Annexure 1",
			),
			(
				"TEST: load the slag into the dumper",
				"TEST: dumper inspected",
				"TEST: spill, dust, fire",
				"TEST Excavator operator",
				"TEST: load in layers, sprinkle water, keep the bucket low",
				"",
			),
		],
		"distribution": [("TEST Stores", "store_t", 1), ("TEST Site Supervisor", "site_sup_t", 2)],
	},
	{
		"job_code": "TEST-ATH",
		"title": "TEST Wheel loader operation in the yard",
		"work": "TEST Loading",
		"area": "TEST Loading Yard",
		"purpose": "TEST: move the wheel loader in the yard without hitting people or equipment.",
		"scope": "TEST: every loader movement in the loading yard.",
		"applicable_to": "TEST: loader operators, banksmen and yard supervisors",
		"definitions": "TEST: banksman is the person who guides the loader when it reverses.",
		"annexure": "",
		"hazards": [
			("TEST: moving vehicle close to people", "TEST: a banksman for every reversing move", "L1"),
			("TEST: moving vehicle close to people", "TEST: reverse alarm and horn working", "L1"),
		],
		"rules": [
			("Do", "TEST: walk around the loader before starting"),
			("Don't", "TEST: do not carry a passenger on the loader"),
		],
		"steps": [
			(
				"TEST: inspect the loader before the shift",
				"TEST: checklist",
				"TEST: defective brakes or alarm",
				"TEST Loader operator",
				"TEST: complete the checklist, report defects",
				"",
			),
			(
				"TEST: reverse with a banksman",
				"TEST: trained banksman",
				"TEST: the loader hits a person",
				"TEST Banksman",
				"TEST: eye contact, agreed hand signals",
				"",
			),
		],
		"distribution": [("TEST Yard Supervisor", "site_sup_t", 1)],
	},
]

DESIGNATIONS = ["TEST Loader Operator", "TEST Fitter", "TEST Store Keeper"]


def email_for(key):
	return f"test.{key}@{DOMAIN}"


def load(password=None, branches=None, head_office=None):
	"""Create the demo data. Safe to run twice: existing TEST records are skipped.

	branches     {branch name: HSE Branch Code} for branches that do not have their code yet. A branch that
	             already has a code keeps it. Branches are never created here.
	head_office  the name of the head office branch, among those in `branches`.
	"""
	frappe.flags.in_demo_seed = True
	sites = _prepare_branches(branches, head_office)
	if not sites:
		return

	_ensure_users(password, sites)
	_ensure_work_orders(sites)
	_ensure_areas(sites)
	_ensure_method_statements(sites)
	_ensure_hiras(sites)
	_ensure_sops(sites)
	frappe.db.commit()
	print(f"Demo data loaded for branches {', '.join(f'{c} ({n})' for c, n in sorted(sites.items()))}.")
	print(f"Test logins end with @{DOMAIN}.")


def _prepare_branches(branches, head_office):
	"""Give the named branches their HSE Branch Code and return {code: branch name} for the site."""
	if isinstance(branches, str):
		branches = json.loads(branches)

	if branches:
		missing = [name for name in branches if not frappe.db.exists("Branch", name)]
		if missing:
			print(f"These branches are not on this site, so nothing was loaded: {', '.join(missing)}.")
			return None
		if head_office and head_office not in branches:
			print(f"The head office {head_office} is not among the branches given, so nothing was loaded.")
			return None

		for name, code in branches.items():
			current = frappe.db.get_value("Branch", name, "hse_branch_code")
			if current and current != code:
				print(f"Branch {name} already has code {current}; leaving it.")
				continue
			clash = frappe.db.get_value("Branch", {"hse_branch_code": code, "name": ["!=", name]}, "name")
			if clash:
				print(f"Code {code} is already used by branch {clash}; {name} is left without it.")
				continue
			if not current:
				print(f"Giving branch {name} the HSE Branch Code {code}.")
				frappe.db.set_value(
					"Branch", name, {"hse_branch_code": code, "hse_is_head_office": int(name == head_office)}
				)

	rows = frappe.get_all(
		"Branch", filters={"hse_branch_code": ["is", "set"]}, fields=["name", "hse_branch_code"]
	)
	if not rows:
		names = ", ".join(frappe.get_all("Branch", pluck="name")) or "none"
		print(
			"No branch has an HSE Branch Code yet, so nothing was loaded.\n"
			f"Branches on this site: {names}.\n"
			"Run again with branches={'<branch name>': '<code>', ...} and head_office='<branch name>'."
		)
		return None
	return {row.hse_branch_code: row.name for row in rows}


def _ensure_users(password, sites):
	for key, role, first_name, codes in USERS:
		missing = [c for c in codes or [] if c not in sites]
		if missing:
			print(f"Skipping {first_name}: no branch with code {', '.join(missing)} on this site.")
			continue
		user_email = email_for(key)
		if frappe.db.exists("User", user_email):
			continue
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": user_email,
				"first_name": first_name,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": role}],
			}
		)
		if password:
			user.new_password = password
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
		for code in codes or []:
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": user_email,
					"allow": "Branch",
					"for_value": sites[code],
				}
			).insert(ignore_permissions=True)


def _ensure_work_orders(sites):
	for values in WORK_ORDERS:
		if values["branch"] not in sites:
			print(f"Skipping work order {values['job_code']}: no branch with code {values['branch']}.")
			continue
		if frappe.db.exists("HSE Work Order", {"job_code": values["job_code"]}):
			continue
		doc = frappe.get_doc({"doctype": "HSE Work Order", **values, "branch": sites[values["branch"]]})
		for line in doc.service_lines:
			if line.uom and not frappe.db.exists("UOM", line.uom):
				line.uom = None
		doc.insert(ignore_permissions=True)


def _ensure_areas(sites):
	for code, job, name, division, details, leader, members in AREAS:
		if code not in sites:
			print(f"Skipping area {name}: no branch with code {code}.")
			continue
		branch = sites[code]
		work_order = frappe.db.get_value("HSE Work Order", {"job_code": job}, "name") if job else None
		if frappe.db.exists("HSE Workplace Area", {"branch": branch, "area_name": name}):
			continue
		team = [
			{"team_role": "Team Lead", "member_name": leader, "category": "SL", "from_date": "2026-04-01"}
		]
		for index, member in enumerate(members, start=1):
			team.append(
				{
					"team_role": f"Member {index}",
					"member_name": member,
					"category": "Worker",
					"from_date": "2026-04-01",
				}
			)
		frappe.get_doc(
			{
				"doctype": "HSE Workplace Area",
				"branch": branch,
				"work_order": work_order,
				"area_name": name,
				"division_type": division,
				"location_details": details,
				"team": team,
			}
		).insert(ignore_permissions=True)


def _ensure_method_statements(sites):
	for values in METHOD_STATEMENTS:
		if values["branch"] not in sites:
			print(
				f"Skipping Method Statement for {values['job_code']}: no branch with code {values['branch']}."
			)
			continue
		work_order = frappe.db.get_value("HSE Work Order", {"job_code": values["job_code"]}, "name")
		if not work_order:
			print(f"Skipping Method Statement for {values['job_code']}: the work order is not on this site.")
			continue
		if frappe.db.exists("HSE Method Statement", {"work_order": work_order}):
			continue

		for designation in DESIGNATIONS:
			if not frappe.db.exists("Designation", designation):
				frappe.get_doc({"doctype": "Designation", "designation_name": designation}).insert(
					ignore_permissions=True
				)

		branch = sites[values["branch"]]
		areas = frappe.get_all(
			"HSE Workplace Area",
			filters={"branch": branch, "area_name": ["in", values["areas"]]},
			pluck="name",
		)
		numbers = [
			{"contact_type": kind, "phone": phone, "details": details}
			for kind, (phone, details) in values["emergency_numbers"].items()
		]
		frappe.get_doc(
			{
				"doctype": "HSE Method Statement",
				"branch": branch,
				"work_order": work_order,
				"areas": [{"area": name} for name in areas],
				"works": values["works"],
				"operations": [{"work": w, "operation": text} for w, text in values["operations"]],
				"equipment": [{"work": w, "equipment": e, "qty": q} for w, e, q in values["equipment"]],
				"manpower": [
					{"work": w, "designation": d, "category": c, "qty": q}
					for w, d, c, q in values["manpower"]
				],
				"ppe": [
					{"activity": activity, "ppe": ppe, "standard": standard}
					for activity, ppe, standard in values["ppe"]
				],
				"sops": [{"work": w, "sop_reference": ref} for w, ref in values["sops"]],
				"hazards": [
					{"work": w, "hazard_risk": hazard, "reference_document": ref}
					for w, hazard, ref in values["hazards"]
				],
				"emergency_procedures": [
					{"emergency_type": t, "procedure_reference": ref}
					for t, ref in values["emergency_procedures"]
				],
				# Left empty when the sample gives none, so the starting rows are filled in.
				**({"emergency_numbers": numbers} if numbers else {}),
			}
		).insert(ignore_permissions=True)


def _ensure_hiras(sites):
	"""A Draft HIRA for each sample work whose Method Statement has been approved.

	The Method Statements are left in Draft so the approval can be walked through. A HIRA needs an
	approved one, so until it is approved the HIRA is skipped, and made the next time this runs.
	"""
	from krl_hse.utils.controlled_document import get_approved_state

	for values in HIRAS:
		work_order = frappe.db.get_value("HSE Work Order", {"job_code": values["job_code"]}, "name")
		if not work_order:
			print(f"Skipping HIRA for {values['job_code']}: the work order is not on this site.")
			continue

		ms = frappe.db.get_value(
			"HSE Method Statement",
			{"work_order": work_order, "workflow_state": get_approved_state()},
			["name", "branch"],
			as_dict=True,
		)
		if not ms:
			print(
				f"Skipping HIRA for {values['job_code']}: its Method Statement is not approved yet. "
				"Approve it, then run the load again."
			)
			continue
		if frappe.db.exists("HSE HIRA", {"method_statement": ms.name}):
			continue

		area = frappe.db.get_value("HSE Workplace Area", {"branch": ms.branch, "area_name": values["area"]})
		lines = [
			{
				"job": job,
				"routine": routine,
				"activity_category": category,
				"activity": activity,
				"hazard_category": hazard_category,
				"hazard": hazard,
				"hazardous_event": event,
				"cause": cause,
				"consequence_impact": consequence_text,
				"impact_area": impact,
				"existing_safeguard": safeguard,
				"recommendation": recommendation,
				"consequence": ratings[0],
				"likelihood": ratings[1],
				"residual_consequence": ratings[2],
				"residual_likelihood": ratings[3],
			}
			for (
				job,
				routine,
				category,
				activity,
				hazard_category,
				hazard,
				event,
				cause,
				consequence_text,
				impact,
				safeguard,
				recommendation,
				ratings,
			) in values["lines"]
		]
		frappe.get_doc(
			{
				"doctype": "HSE HIRA",
				"branch": ms.branch,
				"method_statement": ms.name,
				"area": area,
				"lines": lines,
				"controls": [
					{"line_ref": f"L{n}", "measure_type": kind, "control": text, "hierarchy_level": level}
					for n, kind, text, level in values["controls"]
				],
			}
		).insert(ignore_permissions=True)


def _ensure_sops(sites):
	"""A Draft SOP for each sample work whose Method Statement has been approved.

	Like the HIRA, a SOP needs an approved Method Statement, so it is made the next time this runs
	after the Method Statement has been approved. Its hazards point to the HIRA of the same work when
	one exists.
	"""
	from frappe.utils import add_months, nowdate

	from krl_hse.utils.controlled_document import get_approved_state

	for values in SOPS:
		work_order = frappe.db.get_value("HSE Work Order", {"job_code": values["job_code"]}, "name")
		if not work_order:
			print(f"Skipping SOP for {values['job_code']}: the work order is not on this site.")
			continue

		# The approved Method Statement of this job that has the sample work among its works.
		with_work = frappe.get_all(
			"HSE MS Work",
			filters={"parenttype": "HSE Method Statement", "work_name": values["work"]},
			pluck="parent",
		)
		candidates = (
			frappe.get_all(
				"HSE Method Statement",
				filters={
					"name": ("in", with_work),
					"work_order": work_order,
					"workflow_state": get_approved_state(),
				},
				fields=["name", "branch"],
				order_by="creation asc",
			)
			if with_work
			else []
		)
		# Prefer the one that has a HIRA, so the hazards can point to its lines.
		ms = next((c for c in candidates if frappe.db.exists("HSE HIRA", {"method_statement": c.name})), None)
		ms = ms or (candidates[0] if candidates else None)
		if not ms:
			print(
				f"Skipping SOP for {values['job_code']}: no approved Method Statement has the work {values['work']}. "
				"Approve one, then run the load again."
			)
			continue
		if frappe.db.exists("HSE SOP", {"branch": ms.branch, "sop_title": values["title"]}):
			continue

		hira = frappe.db.get_value("HSE HIRA", {"method_statement": ms.name})
		area = frappe.db.get_value("HSE Workplace Area", {"branch": ms.branch, "area_name": values["area"]})
		frappe.get_doc(
			{
				"doctype": "HSE SOP",
				"branch": ms.branch,
				"method_statement": ms.name,
				"sop_title": values["title"],
				"area": area,
				"purpose": values["purpose"],
				"scope": values["scope"],
				"applicable_to": values["applicable_to"],
				"definitions": values["definitions"],
				"annexure": values["annexure"],
				"validity_date": add_months(nowdate(), 12),
				"works": [{"work": values["work"]}],
				"hazards": [
					{
						"hazard": hazard,
						"mitigation": mitigation,
						"hira": hira if (hira and line) else None,
						"hira_line": line if hira else None,
					}
					for hazard, mitigation, line in values["hazards"]
				],
				"rules": [{"kind": kind, "rule": rule} for kind, rule in values["rules"]],
				"steps": [
					{
						"activity": activity,
						"requirements": requirements,
						"hazard_impact": hazard_impact,
						"responsibility": who,
						"method": how,
						"remarks": remarks,
					}
					for activity, requirements, hazard_impact, who, how, remarks in values["steps"]
				],
				"distribution": [
					{"recipient": recipient, "user": email_for(key), "copies": copies}
					for recipient, key, copies in values["distribution"]
				],
			}
		).insert(ignore_permissions=True)


def clear(delete=0):
	"""Archive the demo data: cancel work orders, disable areas and users.

	With delete=1 the records are removed for good. Do that only after KRL has approved the clean-up.
	"""
	delete = int(delete)

	# SOPs, HIRAs and Method Statements: an approved one cannot be deleted, so it is put back to Draft first. They
	# cannot be archived, so without delete=1 they are left as they are.
	if delete:
		# A SOP and a HIRA go before the Method Statement they belong to.
		for doctype in ("HSE SOP", "HSE HIRA", "HSE Method Statement"):
			for name in frappe.get_all(doctype, filters={"name_of_work": ["like", "TEST%"]}, pluck="name"):
				frappe.db.set_value(doctype, name, "workflow_state", "Draft")
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)

	for name in frappe.get_all("HSE Workplace Area", filters={"area_name": ["like", "TEST%"]}, pluck="name"):
		if delete:
			frappe.delete_doc("HSE Workplace Area", name, force=True, ignore_permissions=True)
		else:
			frappe.db.set_value("HSE Workplace Area", name, "disabled", 1)

	for name in frappe.get_all("HSE Work Order", filters={"job_code": ["like", "TEST%"]}, pluck="name"):
		if delete:
			frappe.delete_doc("HSE Work Order", name, force=True, ignore_permissions=True)
		else:
			frappe.db.set_value("HSE Work Order", name, "status", "Cancelled")

	for key, *_rest in USERS:
		user_email = email_for(key)
		if not frappe.db.exists("User", user_email):
			continue
		if delete:
			for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
				frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
			frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
		else:
			frappe.db.set_value("User", user_email, "enabled", 0)

	if delete:
		for designation in DESIGNATIONS:
			if frappe.db.exists("Designation", designation):
				frappe.delete_doc("Designation", designation, force=True, ignore_permissions=True)

	frappe.db.commit()
	print("Demo data deleted." if delete else "Demo data archived.")
