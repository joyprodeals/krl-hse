const API =
	"krl_hse.hse_health_safety_and_environment.doctype.hse_method_statement.hse_method_statement";

// Tables whose rows pick one of the works of this document.
const WORK_TABLES = ["operations", "equipment", "manpower"];

frappe.ui.form.on("HSE Method Statement", {
	setup(frm) {
		frm.set_query("work_order", () => {
			const filters = { status: ["in", ["Active", "On Hold"]] };
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			return { filters };
		});
		frm.set_query("area", "areas", () => {
			const filters = { disabled: 0 };
			if (frm.doc.branch) filters.branch = frm.doc.branch;
			return { filters };
		});
	},

	onload(frm) {
		if (frm.is_new()) fill_new_document_rows(frm);
	},

	refresh(frm) {
		load_common_works(frm).then(() => set_work_options(frm));
		add_table_buttons(frm);
	},

	branch(frm) {
		// A work belongs to one branch, so a different branch means a different work.
		if (!frm.doc.work_order || !frm.doc.branch) return;
		frappe.db.get_value("HSE Work Order", frm.doc.work_order, "branch").then((r) => {
			if (r.message && r.message.branch !== frm.doc.branch) frm.set_value("work_order", "");
		});
	},

	work_order(frm) {
		if (!frm.doc.work_order) return;
		frappe
			.call({
				method: `${API}.work_order_details`,
				args: { work_order: frm.doc.work_order },
			})
			.then((r) => {
				const details = r.message;
				if (!details) return;
				if (!frm.doc.branch) frm.set_value("branch", details.branch);
				for (const fieldname of [
					"name_of_work",
					"client_name",
					"location",
					"work_start_date",
					"work_end_date",
				]) {
					if (!frm.doc[fieldname] && details[fieldname])
						frm.set_value(fieldname, details[fieldname]);
				}
				if (!(frm.doc.management || []).length) {
					for (const contact of details.management) frm.add_child("management", contact);
					frm.refresh_field("management");
				}
			});
	},
});

frappe.ui.form.on("HSE MS Work", {
	work_name(frm) {
		set_work_options(frm);
	},
	works_remove(frm) {
		set_work_options(frm);
	},
});

frappe.ui.form.on("HSE MS Area", {
	area(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.area) return;
		frappe.call({ method: `${API}.area_details`, args: { area: row.area } }).then((r) => {
			const area = r.message;
			if (!area) return;
			frappe.model.set_value(cdt, cdn, {
				leader_name: area.leader_name,
				leader_designation: area.leader_designation,
				leader_category: area.leader_category,
				details: area.details,
			});
		});
	},
});

function fill_new_document_rows(frm) {
	frappe.call({ method: `${API}.new_document_defaults` }).then((r) => {
		const defaults = r.message;
		if (!defaults) return;
		if (!(frm.doc.ppe || []).length) {
			for (const row of defaults.basic_ppe) frm.add_child("ppe", row);
			frm.refresh_field("ppe");
		}
		if (!(frm.doc.emergency_numbers || []).length) {
			for (const row of defaults.emergency_numbers) frm.add_child("emergency_numbers", row);
			frm.refresh_field("emergency_numbers");
		}
	});
}

function add_table_buttons(frm) {
	const works = frm.fields_dict.works && frm.fields_dict.works.grid;
	if (works && !works.has_hse_buttons) {
		works.has_hse_buttons = true;
		works.add_custom_button(__("Add Services of the Work"), () => {
			if (!frm.doc.work_order) return frappe.msgprint(__("Choose the Work first."));
			frappe
				.call({
					method: `${API}.work_order_details`,
					args: { work_order: frm.doc.work_order },
				})
				.then((r) => {
					const have = new Set(
						(frm.doc.works || []).map((w) => (w.work_name || "").toLowerCase())
					);
					for (const service of (r.message && r.message.services) || []) {
						if (!have.has(service.toLowerCase()))
							frm.add_child("works", { work_name: service });
					}
					frm.refresh_field("works");
					set_work_options(frm);
				});
		});
	}

	const areas = frm.fields_dict.areas && frm.fields_dict.areas.grid;
	if (areas && !areas.has_hse_buttons) {
		areas.has_hse_buttons = true;
		areas.add_custom_button(__("Add Areas of the Work"), () => {
			if (!frm.doc.work_order) return frappe.msgprint(__("Choose the Work first."));
			frappe
				.call({ method: `${API}.work_areas`, args: { work_order: frm.doc.work_order } })
				.then((r) => {
					const have = new Set((frm.doc.areas || []).map((a) => a.area));
					for (const area of r.message || []) {
						if (have.has(area.area)) continue;
						frm.add_child("areas", {
							area: area.area,
							leader_name: area.leader_name,
							leader_designation: area.leader_designation,
							leader_category: area.leader_category,
							details: area.details,
						});
					}
					frm.refresh_field("areas");
				});
		});
	}
}

function load_common_works(frm) {
	if (frm._common_works) return Promise.resolve();
	return frappe.db
		.get_list("HSE Common Work", { fields: ["name"], limit: 100, order_by: "name" })
		.then((rows) => {
			frm._common_works = rows.map((row) => row.name);
		});
}

// The works of this document, then the common names, as the choices in every work column.
function set_work_options(frm) {
	const own = (frm.doc.works || []).map((row) => row.work_name).filter(Boolean);
	const common = (frm._common_works || []).filter((name) => !own.includes(name));
	const options = ["", ...own, ...common].join("\n");

	for (const table of WORK_TABLES) {
		const field = frm.fields_dict[table];
		if (!field) continue;
		field.grid.update_docfield_property("work", "options", options);
		field.grid.refresh();
	}
}
