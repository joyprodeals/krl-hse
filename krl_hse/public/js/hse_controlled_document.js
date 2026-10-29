// What every controlled planning document (Method Statement, HIRA, SOP, JHA) shares on its form:
// the revision banner, the Start Revision button and a way to see all revisions of one number.
// The list of controlled document types comes from `hse_controlled_doctypes` in hooks.py, sent to
// the browser at login.
$(document).on("form-refresh", (event, frm) => {
	const controlled = (frappe.boot && frappe.boot.hse_controlled_doctypes) || [];
	if (!controlled.includes(frm.doctype) || frm.is_new()) return;

	const docname = frm.docname;
	frappe
		.call({
			method: "krl_hse.utils.controlled_document.revision_status",
			args: { doctype: frm.doctype, name: docname },
		})
		.then((r) => {
			const status = r.message;
			// The form may have moved on to another record while this call was running.
			if (!status || frm.docname !== docname) return;
			show_revision_state(frm, status);
		});
});

function show_revision_state(frm, status) {
	frm.set_intro("");

	if (!status.is_latest) {
		frm.set_intro(
			__("This revision is not the latest. Revision {0} is {1}.", [
				frappe.utils.get_form_link(frm.doctype, status.latest, true),
				__(status.latest_state || ""),
			]),
			"orange"
		);
	}

	frm.add_custom_button(
		__("All Revisions"),
		() => frappe.set_route("List", frm.doctype, { document_number: status.document_number }),
		__("Revision")
	);

	if (status.can_revise) {
		frm.add_custom_button(__("Start Revision"), () => start_revision(frm), __("Revision"));
	}
}

function start_revision(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Start Revision {0}", [(frm.doc.revision_number || 0) + 1]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"The new revision starts as a draft. This one stays in force until the new revision is approved."
				)}</p>`,
			},
			{
				fieldname: "revision_trigger",
				fieldtype: "Link",
				options: "HSE Revision Trigger",
				label: __("What Triggered This Revision"),
				reqd: 1,
			},
			{
				fieldname: "source_document",
				fieldtype: "Data",
				label: __("Source Document"),
				description: __("For example the CAPA number or the client letter"),
			},
			{
				fieldname: "revision_remark",
				fieldtype: "Small Text",
				label: __("What Changed and Why"),
				reqd: 1,
			},
		],
		primary_action_label: __("Start Revision"),
		primary_action(values) {
			frappe
				.call({
					method: "krl_hse.utils.controlled_document.start_revision",
					args: { doctype: frm.doctype, name: frm.docname, ...values },
					freeze: true,
				})
				.then((r) => {
					dialog.hide();
					if (r.message) frappe.set_route("Form", frm.doctype, r.message);
				});
		},
	});
	dialog.show();
}
