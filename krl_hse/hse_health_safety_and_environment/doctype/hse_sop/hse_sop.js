const API = "krl_hse.utils.planning_document";
const SOP_API = "krl_hse.hse_health_safety_and_environment.doctype.hse_sop.hse_sop";
const RULES_API = "krl_hse.utils.controlled_document.planning_rules";

frappe.ui.form.on("HSE SOP", {
	setup(frm) {
		frm.set_query("method_statement", () => {
			const filters = {};
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			// With the rule "Approved only" the list offers only approved Method Statements.
			if (frm._parent_rule === "Approved only" && frm._approved_state)
				filters.workflow_state = frm._approved_state;
			return { filters };
		});

		frm.set_query("area", () => {
			const filters = { disabled: 0 };
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			if (frm.doc.work_order) filters.work_order = ["in", [frm.doc.work_order, ""]];
			return { filters };
		});

		frm.set_query("hira", "hazards", () => {
			const filters = {};
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			if (frm.doc.method_statement) filters.method_statement = frm.doc.method_statement;
			return { filters };
		});
	},

	refresh(frm) {
		Promise.all([load_settings(frm), load_common_works(frm), load_ms_works(frm)]).then(() => {
			frm.set_df_property(
				"method_statement",
				"reqd",
				frm._parent_rule === "Not required" ? 0 : 1
			);
			set_work_options(frm);
			add_grid_buttons(frm);
			add_basic_ppe(frm);
		});
	},

	branch(frm) {
		// A Method Statement belongs to one branch, so a different branch means a different one.
		if (!frm.doc.method_statement || !frm.doc.branch) return;
		frappe.db.get_value("HSE Method Statement", frm.doc.method_statement, "branch").then((r) => {
			if (r.message && r.message.branch !== frm.doc.branch) {
				frm.set_value("method_statement", "");
				frm.set_value("work_order", "");
			}
		});
	},

	method_statement(frm) {
		frm._ms_works = null;
		if (!frm.doc.method_statement) return set_work_options(frm);

		frappe
			.call({ method: `${API}.method_statement_details`, args: { method_statement: frm.doc.method_statement } })
			.then((r) => {
				const details = r.message;
				if (!details) return;
				frm._ms_works = details.works || [];
				if (!frm.doc.branch) frm.set_value("branch", details.branch);
				frm.set_value("work_order", details.work_order);
				if (!frm.doc.name_of_work) frm.set_value("name_of_work", details.name_of_work);
				if (!frm.doc.client_name) frm.set_value("client_name", details.client_name);
				if (!frm.doc.area && details.areas.length === 1) frm.set_value("area", details.areas[0]);
				if (frm.is_new() && details.client_format_applies && !frm.doc.client_format_applies) {
					frm.set_value("client_format_applies", 1);
					frm.set_value("client_format_reference", details.client_format_reference);
				}
				set_work_options(frm);
			});
	},
});

frappe.ui.form.on("HSE SOP Step", {
	steps_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.step_ref) row.step_ref = next_step_ref(frm);
		frm.refresh_field("steps");
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

function load_common_works(frm) {
	if (frm._common_works) return Promise.resolve();
	return frappe.db
		.get_list("HSE Common Work", { fields: ["name"], limit: 100, order_by: "name" })
		.then((rows) => {
			frm._common_works = rows.map((row) => row.name);
		});
}

// The works of the chosen Method Statement, for the Works table.
function load_ms_works(frm) {
	if (frm._ms_works || !frm.doc.method_statement) return Promise.resolve();
	return frappe
		.call({ method: `${API}.method_statement_details`, args: { method_statement: frm.doc.method_statement } })
		.then((r) => {
			frm._ms_works = (r.message && r.message.works) || [];
		});
}

// The works of the Method Statement, then the common names, as the choices in the Works table.
function set_work_options(frm) {
	const own = frm._ms_works || [];
	const common = (frm._common_works || []).filter((name) => !own.includes(name));
	const field = frm.fields_dict.works;
	if (!field) return;
	field.grid.update_docfield_property("work", "options", ["", ...own, ...common].join("\n"));
	field.grid.refresh();
}

function add_grid_buttons(frm) {
	const works = frm.fields_dict.works && frm.fields_dict.works.grid;
	if (works && !works.has_hse_buttons) {
		works.has_hse_buttons = true;
		works.add_custom_button(__("Add All Works of the Method Statement"), () => {
			if (!frm.doc.method_statement) return frappe.msgprint(__("Choose the Method Statement first."));
			const present = (frm.doc.works || []).map((row) => row.work);
			for (const work of frm._ms_works || []) {
				if (!present.includes(work)) frm.add_child("works", { work });
			}
			frm.refresh_field("works");
		});
	}

	const hazards = frm.fields_dict.hazards && frm.fields_dict.hazards.grid;
	if (hazards && !hazards.has_hse_buttons) {
		hazards.has_hse_buttons = true;
		hazards.add_custom_button(__("Add Hazards from HIRA"), () => pick_hira(frm));
	}
}

// Offer the HIRAs of this Method Statement and copy a chosen one's hazards and control measures.
function pick_hira(frm) {
	const filters = {};
	if (frm.doc.branch) filters.branch = frm.doc.branch;
	if (frm.doc.method_statement) filters.method_statement = frm.doc.method_statement;

	const dialog = new frappe.ui.Dialog({
		title: __("Add Hazards from HIRA"),
		fields: [
			{
				fieldname: "hira",
				fieldtype: "Link",
				options: "HSE HIRA",
				label: __("HIRA"),
				reqd: 1,
				get_query: () => ({ filters }),
				description: __(
					"One row is added for each control measure of each line. Remove the ones that do not apply to this SOP."
				),
			},
		],
		primary_action_label: __("Add"),
		primary_action({ hira }) {
			frappe.call({ method: `${SOP_API}.hazards_from_hira`, args: { hira }, freeze: true }).then((r) => {
				const rows = r.message || [];
				const have = new Set(
					(frm.doc.hazards || []).map((row) => [row.hira, row.hira_line, row.mitigation].join("|"))
				);
				let added = 0;
				for (const row of rows) {
					if (have.has([row.hira, row.hira_line, row.mitigation].join("|"))) continue;
					frm.add_child("hazards", row);
					added += 1;
				}
				frm.refresh_field("hazards");
				dialog.hide();
				frappe.show_alert({
					message: added
						? __("{0} hazard rows added from {1}", [added, hira])
						: __("Nothing to add: the HIRA has no control measures or safeguards that are not already listed."),
					indicator: added ? "green" : "orange",
				});
			});
		},
	});
	dialog.show();
}

// A new SOP starts with the basic PPE, as the server also does on the first save.
function add_basic_ppe(frm) {
	if (!frm.is_new() || (frm.doc.ppe || []).length || frm._basic_ppe_added) return;
	frm._basic_ppe_added = true;
	frappe.call({ method: `${SOP_API}.new_document_defaults` }).then((r) => {
		for (const row of (r.message && r.message.basic_ppe) || []) frm.add_child("ppe", row);
		frm.refresh_field("ppe");
	});
}

function next_step_ref(frm) {
	const numbers = (frm.doc.steps || [])
		.map((row) => /^S(\d+)$/.exec(row.step_ref || ""))
		.filter(Boolean)
		.map((match) => parseInt(match[1], 10));
	return `S${Math.max(0, ...numbers) + 1}`;
}
