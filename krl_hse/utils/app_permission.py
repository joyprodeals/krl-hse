import frappe


def has_app_permission():
    """Show KRL HSE only to users who can read HSE Settings."""
    if frappe.session.user == "Administrator":
        return True

    return frappe.has_permission("HSE Settings", ptype="read")
