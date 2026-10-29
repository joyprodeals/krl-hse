import frappe


def boot_session(bootinfo):
	"""Tell the browser which HSE document types carry a branch and which are controlled (see hooks.py)."""
	bootinfo.hse_branch_doctypes = frappe.get_hooks("hse_branch_doctypes")
	bootinfo.hse_controlled_doctypes = frappe.get_hooks("hse_controlled_doctypes")
