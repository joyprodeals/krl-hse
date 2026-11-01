const JHA_API = "krl_hse.hse_health_safety_and_environment.doctype.hse_jha.hse_jha";
const RULES_API = "krl_hse.utils.controlled_document.planning_rules";

frappe.ui.form.on("HSE JHA", {
	setup(frm) {
		frm.set_query("sop", () => {
			const filters = {};
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			// With the rule "Approved only" the list offers only SOPs in force: approved and not expired.
			if (frm._parent_rule === "Approved only" && frm._approved_state) {
				filters.workflow_state = frm._approved_state;
				filters.validity_date = [">=", frappe.datetime.get_today()];
			}
			return { filters };
		});

		frm.set_query("area", () => {
			const filters = { disabled: 0 };
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			if (frm.doc.work_order) filters.work_order = ["in", [frm.doc.work_order, ""]];
			return { filters };
		});

		// Other SOPs the job follows may come from any branch (a company-wide SOP, for example).
		frm.set_query("sop", "reference_sops", () => ({
			filters: { workflow_state: frm._approved_state || "Approved" },
		}));

		frm.set_query("hira", "hazards", () => {
			const filters = {};
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			if (frm.doc.method_statement) filters.method_statement = frm.doc.method_statement;
			return { filters };
		});
	},

	refresh(frm) {
		load_settings(frm).then(() => {
			set_reference_options(frm);
			add_grid_buttons(frm);
			fill_new_form(frm);
		});
	},

	branch(frm) {
		// A SOP belongs to one branch, so a different branch means a different one.
		if (!frm.doc.sop || !frm.doc.branch) return;
		frappe.db.get_value("HSE SOP", frm.doc.sop, "branch").then((r) => {
			if (r.message && r.message.branch !== frm.doc.branch) frm.set_value("sop", "");
		});
	},

	sop(frm) {
		frm._sop = null;
		if (!frm.doc.sop) return;
		get_sop(frm).then((details) => {
			if (!details) return;
			if (!frm.doc.branch) frm.set_value("branch", details.branch);
			frm.set_value("method_statement", details.method_statement);
			frm.set_value("work_order", details.work_order);
			if (!frm.doc.area) frm.set_value("area", details.area);
			if (!frm.doc.jha_title) frm.set_value("jha_title", details.title);
			if (!frm.doc.name_of_work) frm.set_value("name_of_work", details.name_of_work);
			if (!frm.doc.client_name) frm.set_value("client_name", details.client_name);
			frm._sop_filled = false;
			fill_new_form(frm);
		});
	},
});

frappe.ui.form.on("HSE JHA Step", {
	steps_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.step_ref) row.step_ref = next_ref(frm.doc.steps, "step_ref", "A");
		frm.refresh_field("steps");
		set_reference_options(frm);
	},
	steps_remove(frm) {
		set_reference_options(frm);
	},
	activity(frm) {
		set_reference_options(frm);
	},
});

frappe.ui.form.on("HSE JHA Hazard", {
	hazards_add(frm, cdt, cdn) {
		// Most hazards are for the step that was last worked on.
		const row = locals[cdt][cdn];
		const hazards = frm.doc.hazards || [];
		const steps = frm.doc.steps || [];
		if (!row.hazard_ref) row.hazard_ref = next_ref(hazards, "hazard_ref", "H");
		if (!row.step_ref) {
			const previous = hazards.length > 1 ? hazards[hazards.length - 2].step_ref : "";
			row.step_ref = previous || (steps.length ? steps[0].step_ref : "");
		}
		frm.refresh_field("hazards");
		set_reference_options(frm);
	},
	hazards_remove(frm) {
		set_reference_options(frm);
	},
});

frappe.ui.form.on("HSE JHA Control", {
	controls_add(frm, cdt, cdn) {
		// Most control measures are for the hazard that was last worked on.
		const hazards = frm.doc.hazards || [];
		const row = locals[cdt][cdn];
		if (!row.hazard_ref && hazards.length) row.hazard_ref = hazards[hazards.length - 1].hazard_ref;
		frm.refresh_field("controls");
	},
});

function load_settings(frm) {
	if (frm._settings_loaded) return Promise.resolve();
	return frappe.call({ method: RULES_API }).then((r) => {
		const rules = r.message || {};
		frm._parent_rule = rules.parent_document_rule || "Approved only";
		frm._approved_state = rules.approved_state || "Approved";
		frm._settings_loaded = true;
	});
}

// What the chosen SOP gives the JHA: its steps, PPE and the emergency numbers of its Method Statement.
function get_sop(frm) {
	if (frm._sop && frm._sop.name === frm.doc.sop) return Promise.resolve(frm._sop.details);
	if (!frm.doc.sop) return Promise.resolve(null);
	const name = frm.doc.sop;
	return frappe.call({ method: `${JHA_API}.get_sop_details`, args: { sop: name } }).then((r) => {
		frm._sop = { name, details: r.message };
		return r.message;
	});
}

// A new JHA starts with the steps and PPE of its SOP and the emergency numbers of its Method Statement,
// as the server also does on the first save.
function fill_new_form(frm) {
	if (!frm.is_new() || !frm.doc.sop || frm._sop_filled) return;
	frm._sop_filled = true;
	get_sop(frm).then((details) => {
		if (!details) return;
		if (!(frm.doc.steps || []).length) {
			for (const step of details.steps) frm.add_child("steps", { ...step, step_ref: next_ref(frm.doc.steps, "step_ref", "A") });
			frm.refresh_field("steps");
		}
		if (!(frm.doc.ppe || []).length) {
			for (const row of details.ppe) frm.add_child("ppe", row);
			frm.refresh_field("ppe");
		}
		if (!(frm.doc.emergency_contacts || []).length) {
			for (const row of details.contacts) frm.add_child("emergency_contacts", row);
			frm.refresh_field("emergency_contacts");
		}
		set_reference_options(frm);
	});
}

// Hazards pick their step from the steps, and control measures pick their hazard from the hazards.
function set_reference_options(frm) {
	const steps = (frm.doc.steps || []).map((row) => row.step_ref).filter(Boolean);
	const hazards = (frm.doc.hazards || []).map((row) => row.hazard_ref).filter(Boolean);
	const pairs = [
		["hazards", "step_ref", steps],
		["controls", "hazard_ref", hazards],
	];
	for (const [table, fieldname, refs] of pairs) {
		const field = frm.fields_dict[table];
		if (!field) continue;
		field.grid.update_docfield_property(fieldname, "options", ["", ...refs].join("\n"));
		field.grid.refresh();
	}
}

function add_grid_buttons(frm) {
	const steps = frm.fields_dict.steps && frm.fields_dict.steps.grid;
	if (steps && !steps.has_hse_buttons) {
		steps.has_hse_buttons = true;
		steps.add_custom_button(__("Add Steps from SOP"), () => add_sop_steps(frm));
	}

	const hazards = frm.fields_dict.hazards && frm.fields_dict.hazards.grid;
	if (hazards && !hazards.has_hse_buttons) {
		hazards.has_hse_buttons = true;
		hazards.add_custom_button(__("Add Hazards from HIRA"), () => pick_hira(frm));
	}
}

// Copy the steps of the SOP that the JHA does not have yet.
function add_sop_steps(frm) {
	if (!frm.doc.sop) return frappe.msgprint(__("Choose the SOP first."));
	get_sop(frm).then((details) => {
		const present = (frm.doc.steps || []).map((row) => row.sop_step_ref).filter(Boolean);
		let added = 0;
		for (const step of details.steps) {
			if (present.includes(step.sop_step_ref)) continue;
			frm.add_child("steps", { ...step, step_ref: next_ref(frm.doc.steps, "step_ref", "A") });
			added += 1;
		}
		frm.refresh_field("steps");
		set_reference_options(frm);
		frappe.show_alert({
			message: added
				? __("{0} steps added from {1}", [added, frm.doc.sop])
				: __("Nothing to add: every step of the SOP is already in this JHA."),
			indicator: added ? "green" : "orange",
		});
	});
}

// Choose a step, a HIRA and some of its lines. Their hazards and control measures are copied to the step.
function pick_hira(frm) {
	const steps = (frm.doc.steps || []).filter((row) => row.step_ref);
	if (!steps.length) return frappe.msgprint(__("Add the steps of the job first."));

	const filters = {};
	if (frm.doc.branch) filters.branch = frm.doc.branch;
	if (frm.doc.method_statement) filters.method_statement = frm.doc.method_statement;

	const dialog = new frappe.ui.Dialog({
		title: __("Add Hazards from HIRA"),
		fields: [
			{
				fieldname: "step",
				fieldtype: "Select",
				label: __("Add to Step"),
				reqd: 1,
				options: steps.map((row) => ({
					value: row.step_ref,
					label: `${row.step_ref}: ${(row.activity || "").slice(0, 60)}`,
				})),
			},
			{
				fieldname: "hira",
				fieldtype: "Link",
				options: "HSE HIRA",
				label: __("HIRA"),
				reqd: 1,
				get_query: () => ({ filters }),
				onchange: () => load_hira_lines(dialog),
			},
			{
				fieldname: "lines",
				fieldtype: "MultiCheck",
				label: __("Lines to Copy"),
				options: [],
				columns: 1,
				select_all: true,
				sort_options: false,
				description: __("Each line becomes a hazard of the step, with its control measures."),
			},
		],
		primary_action_label: __("Add"),
		primary_action({ step, hira }) {
			const lines = dialog.get_field("lines").get_checked_options();
			if (!lines.length) return frappe.msgprint(__("Tick at least one line."));
			frappe
				.call({ method: `${JHA_API}.hazards_from_hira`, args: { hira, lines }, freeze: true })
				.then((r) => {
					const added = add_hira_hazards(frm, step, r.message || []);
					frm.refresh_field("hazards");
					frm.refresh_field("controls");
					set_reference_options(frm);
					dialog.hide();
					frappe.show_alert({
						message: added
							? __("{0} hazards added to step {1} from {2}", [added, step, hira])
							: __("Nothing to add: those lines are already in this JHA."),
						indicator: added ? "green" : "orange",
					});
				});
		},
	});
	dialog.show();
}

function load_hira_lines(dialog) {
	const hira = dialog.get_value("hira");
	const field = dialog.get_field("lines");
	if (!hira) {
		field.df.options = [];
		return field.refresh();
	}
	frappe.call({ method: `${JHA_API}.hira_lines`, args: { hira } }).then((r) => {
		field.df.options = (r.message || []).map((line) => ({
			value: line.line_ref,
			label: `${line.line_ref}: ${line.hazard}${line.activity ? ` (${line.activity.slice(0, 50)})` : ""}`,
			checked: 1,
		}));
		field.refresh();
	});
}

// A line that is already copied (same HIRA, same line, same step) is not copied twice.
function add_hira_hazards(frm, step, items) {
	const have = new Set(
		(frm.doc.hazards || []).map((row) => [row.step_ref, row.hira, row.hira_line].join("|"))
	);
	let added = 0;
	for (const item of items) {
		const hazard = item.hazard;
		if (have.has([step, hazard.hira, hazard.hira_line].join("|"))) continue;

		const ref = next_ref(frm.doc.hazards, "hazard_ref", "H");
		frm.add_child("hazards", { ...hazard, step_ref: step, hazard_ref: ref });
		for (const control of item.controls) frm.add_child("controls", { ...control, hazard_ref: ref });
		added += 1;
	}
	return added;
}

function next_ref(rows, fieldname, prefix) {
	const numbers = (rows || [])
		.map((row) => new RegExp(`^${prefix}(\\d+)$`).exec(row[fieldname] || ""))
		.filter(Boolean)
		.map((match) => parseInt(match[1], 10));
	return `${prefix}${Math.max(0, ...numbers) + 1}`;
}
