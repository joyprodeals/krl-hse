frappe.ui.form.on("HSE Risk Matrix", {
	refresh(frm) {
		const html = (frm.doc.__onload || {}).matrix_preview || "";
		frm.fields_dict.matrix_preview.$wrapper.html(html);

		if (!frm.doc.confirmed_by_krl) {
			frm.set_intro(
				__(
					"Provisional: KRL has not confirmed this matrix yet. Every HIRA shows this until the Confirmed by KRL tick is set."
				),
				"orange"
			);
		}
	},
});
