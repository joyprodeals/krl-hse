const API = "krl_hse.utils.planning_document";
const RISK_API = "krl_hse.utils.risk.get_risk_matrix";
const RULES_API = "krl_hse.utils.controlled_document.planning_rules";

frappe.ui.form.on("HSE HIRA", {
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
	},

	refresh(frm) {
		Promise.all([load_settings(frm), load_matrix(frm)]).then(() => {
			frm.set_df_property(
				"method_statement",
				"reqd",
				frm._parent_rule === "Not required" ? 0 : 1
			);
			show_matrix_notice(frm);
			set_line_options(frm);
			watch_severity_cells(frm);
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
		if (!frm.doc.method_statement) return;
		frappe
			.call({ method: `${API}.method_statement_details`, args: { method_statement: frm.doc.method_statement } })
			.then((r) => {
				const details = r.message;
				if (!details) return;
				if (!frm.doc.branch) frm.set_value("branch", details.branch);
				frm.set_value("work_order", details.work_order);
				if (!frm.doc.name_of_work) frm.set_value("name_of_work", details.name_of_work);
				if (!frm.doc.client_name) frm.set_value("client_name", details.client_name);
				if (!frm.doc.area && details.areas.length === 1) frm.set_value("area", details.areas[0]);
				if (frm.is_new() && details.client_format_applies && !frm.doc.client_format_applies) {
					frm.set_value("client_format_applies", 1);
					frm.set_value("client_format_reference", details.client_format_reference);
				}
			});
	},
});

frappe.ui.form.on("HSE HIRA Line", {
	lines_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.line_ref) row.line_ref = next_line_ref(frm);
		frm.refresh_field("lines");
		set_line_options(frm);
	},
	lines_remove(frm) {
		set_line_options(frm);
	},
	consequence(frm, cdt, cdn) {
		rate_row(frm, cdt, cdn, "");
	},
	likelihood(frm, cdt, cdn) {
		rate_row(frm, cdt, cdn, "");
	},
	residual_consequence(frm, cdt, cdn) {
		rate_row(frm, cdt, cdn, "residual_");
	},
	residual_likelihood(frm, cdt, cdn) {
		rate_row(frm, cdt, cdn, "residual_");
	},
});

frappe.ui.form.on("HSE HIRA Control", {
	controls_add(frm, cdt, cdn) {
		// Most control measures are for the line that was last worked on.
		const lines = frm.doc.lines || [];
		const row = locals[cdt][cdn];
		if (!row.line_ref && lines.length) row.line_ref = lines[lines.length - 1].line_ref;
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

function load_matrix(frm) {
	if (frm._risk) return Promise.resolve();
	return frappe.call({ method: RISK_API }).then((r) => {
		frm._risk = r.message;
	});
}

function show_matrix_notice(frm) {
	if (frm._risk && !frm._risk.confirmed) {
		frm.set_intro(
			__(
				"The risk matrix is provisional: KRL has not confirmed which ratings give which severity yet. Ratings may change when it is confirmed."
			),
			"orange"
		);
	}
}

// The severity follows from the consequence and likelihood, as the risk matrix says.
function rate_row(frm, cdt, cdn, prefix) {
	const risk = frm._risk;
	if (!risk) return;

	const row = locals[cdt][cdn];
	const consequence = row[`${prefix}consequence`];
	const likelihood = row[`${prefix}likelihood`];
	const level = risk.likelihoods.find((l) => l.name === likelihood);

	frappe.model.set_value(cdt, cdn, {
		[`${prefix}probability`]: level ? level.level : 0,
		[`${prefix}severity`]: consequence && likelihood ? risk.cells[`${consequence}|${likelihood}`] || "" : "",
	});
}

function next_line_ref(frm) {
	const numbers = (frm.doc.lines || [])
		.map((row) => /^L(\d+)$/.exec(row.line_ref || ""))
		.filter(Boolean)
		.map((match) => parseInt(match[1], 10));
	return `L${Math.max(0, ...numbers) + 1}`;
}

// The control measures pick the line they are for from the lines of this HIRA.
function set_line_options(frm) {
	const refs = (frm.doc.lines || []).map((row) => row.line_ref).filter(Boolean);
	const field = frm.fields_dict.controls;
	if (!field) return;
	field.grid.update_docfield_property("line_ref", "options", ["", ...refs].join("\n"));
	field.grid.refresh();
}

// A severity in the lines grid is shown as a pill in its own colour, set on the severity master.
function watch_severity_cells(frm) {
	const field = frm.fields_dict.lines;
	if (!field || !frm._risk) return;

	if (!frm._severity_observer) {
		// The grid redraws a row whenever a value changes, so the colours are applied again each time.
		frm._severity_observer = new MutationObserver(() => colour_severity_cells(frm));
		frm._severity_observer.observe(field.$wrapper[0], { childList: true, subtree: true });
	}
	colour_severity_cells(frm);
}

function colour_severity_cells(frm) {
	const field = frm.fields_dict.lines;
	if (!field || !frm._risk) return;

	for (const fieldname of ["severity", "residual_severity"]) {
		for (const cell of field.$wrapper[0].querySelectorAll(
			`.grid-body .grid-static-col[data-fieldname="${fieldname}"] .static-area`
		)) {
			const info = frm._risk.severities[(cell.innerText || "").trim()];
			if (!info) continue;
			const colour = info.colour || "#9e9e9e";
			cell.style.cssText = `display:inline-block;padding:0 8px;border-radius:10px;background:${colour};color:${text_colour(colour)};`;
		}
	}
}

function text_colour(hex) {
	const value = (hex || "#9e9e9e").replace("#", "");
	const full = value.length === 3 ? value.replace(/./g, "$&$&") : value;
	const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
	return (r * 299 + g * 587 + b * 114) / 1000 > 128 ? "#000000" : "#ffffff";
}
