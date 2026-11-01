"""The risk scales and the risk matrix, read from the masters so nothing about them is fixed in code.

A HIRA line is rated with a consequence and a likelihood. The risk matrix (HSE Risk Matrix) says which
severity that pair gives, and HSE Severity Level says what the severity means.
"""

import frappe
from frappe import _
from frappe.utils import cint

# Used only when a severity has no colour of its own.
FALLBACK_COLOUR = "#9e9e9e"


def check_scale_level(doc):
	"""A scale level (likelihood or consequence) is a number of 1 or more that no other level uses."""
	if cint(doc.level) < 1:
		frappe.throw(_("Level must be 1 or more."))

	clash = frappe.db.get_value(doc.doctype, {"level": doc.level, "name": ["!=", doc.name]}, "name")
	if clash:
		frappe.throw(_("{0} already uses level {1}.").format(clash, doc.level))


def severity_map():
	"""{(consequence, likelihood): severity} from the risk matrix."""
	matrix = frappe.get_cached_doc("HSE Risk Matrix")
	return {(row.consequence, row.likelihood): row.severity for row in matrix.cells}


def severity_for(consequence, likelihood):
	"""The severity a consequence and likelihood give, or None when one is empty or the pair is not in the matrix."""
	if not consequence or not likelihood:
		return None
	return severity_map().get((consequence, likelihood))


def severity_details():
	"""{severity: {level, harm, colour, stops_work, action_required}} for every severity."""
	rows = frappe.get_all(
		"HSE Severity Level",
		fields=["name", "level", "harm", "colour", "stops_work", "action_required"],
		order_by="level",
	)
	return {row.pop("name"): row for row in rows}


@frappe.whitelist()
def get_risk_matrix():
	"""Everything the browser needs to rate a line without a round trip."""
	frappe.has_permission("HSE Risk Matrix", "read", throw=True)
	matrix = frappe.get_cached_doc("HSE Risk Matrix")
	return {
		"cells": {f"{c}|{l}": s for (c, l), s in severity_map().items()},
		"severities": severity_details(),
		"consequences": frappe.get_all(
			"HSE Consequence Level", fields=["name", "level", "definition"], order_by="level"
		),
		"likelihoods": frappe.get_all(
			"HSE Likelihood Level", fields=["name", "level", "definition"], order_by="level"
		),
		"confirmed": cint(matrix.confirmed_by_krl),
	}


def text_colour(background):
	"""Black or white, whichever reads better on a hex background."""
	value = (background or FALLBACK_COLOUR).lstrip("#")
	if len(value) == 3:
		value = "".join(ch * 2 for ch in value)
	try:
		red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
	except ValueError:
		return "#000000"
	return "#000000" if (red * 299 + green * 587 + blue * 114) / 1000 > 128 else "#ffffff"


def matrix_preview_html():
	"""The matrix as a coloured grid: likelihood down the side (most likely at the top), consequence across."""
	cells = severity_map()
	details = severity_details()
	consequences = frappe.get_all("HSE Consequence Level", fields=["name", "level"], order_by="level")
	likelihoods = frappe.get_all("HSE Likelihood Level", fields=["name", "level"], order_by="level desc")

	head = "".join(f"<th>{frappe.utils.escape_html(c.name)}</th>" for c in consequences)
	rows = []
	for lik in likelihoods:
		tds = []
		for con in consequences:
			severity = cells.get((con.name, lik.name))
			info = details.get(severity, {})
			colour = info.get("colour") or FALLBACK_COLOUR
			label = frappe.utils.escape_html(severity or "?")
			tds.append(
				f'<td style="background:{colour};color:{text_colour(colour)};text-align:center">{label}</td>'
			)
		rows.append(f"<tr><th>{frappe.utils.escape_html(lik.name)}</th>{''.join(tds)}</tr>")

	return (
		'<table class="table table-bordered" style="max-width:720px">'
		f"<thead><tr><th>Likelihood / Consequence</th>{head}</tr></thead>"
		f"<tbody>{''.join(rows)}</tbody></table>"
	)
