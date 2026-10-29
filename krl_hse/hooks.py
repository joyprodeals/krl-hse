app_name = "krl_hse"
app_title = "KRL HSE"
app_publisher = "Stackerbee Technologies Pvt. Ltd."
app_description = "Health, Safety and Environment management for KRL Infratech"
app_email = "Jaywardhan.s@stackerbee.com"
app_license = "custom"

# Apps
# ------------------

required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "krl_hse",
# 		"logo": "/assets/krl_hse/logo.png",
# 		"title": "KRL HSE",
# 		"route": "/krl_hse",
# 		"has_permission": "krl_hse.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `krl_hse/dock/krl_hse/krl_hse.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/krl_hse/css/krl_hse.css"
app_include_js = [
	"/assets/krl_hse/js/hse_branch.js",
	"/assets/krl_hse/js/hse_controlled_document.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/krl_hse/css/krl_hse.css"
# web_include_js = "/assets/krl_hse/js/krl_hse.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "krl_hse/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "krl_hse/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# Every function in krl_hse/utils/printing.py is available to the print format templates.
jinja = {
	"methods": ["krl_hse.utils.printing"],
}

# Installation
# ------------

# before_install = "krl_hse.install.before_install"
after_install = "krl_hse.setup.install.after_install"
after_migrate = "krl_hse.setup.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "krl_hse.uninstall.before_uninstall"
# after_uninstall = "krl_hse.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "krl_hse.utils.before_app_install"
# after_app_install = "krl_hse.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "krl_hse.utils.before_app_uninstall"
# after_app_uninstall = "krl_hse.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "krl_hse.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "krl_hse.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["krl_hse.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# Every HSE document type that carries a `branch` field. Add each new one here, and the
# branch rules in krl_hse/utils/branch_access.py apply to it. A test fails if one is missed.
hse_branch_doctypes = [
	"HSE Work Order",
	"HSE Workplace Area",
	"HSE Method Statement",
]

# Planning documents with revisions and a lifecycle (krl_hse/utils/controlled_document.py). Each
# must also be in hse_branch_doctypes above. A test fails if one is missed.
hse_controlled_doctypes = [
	"HSE Method Statement",
]

permission_query_conditions = {
	doctype: "krl_hse.utils.branch_access.permission_query_conditions" for doctype in hse_branch_doctypes
}

has_permission = {doctype: "krl_hse.utils.branch_access.has_permission" for doctype in hse_branch_doctypes}

# Document Events
# ---------------
# Hook on document methods and events

boot_session = "krl_hse.utils.boot.boot_session"

doctype_js = {"Branch": "public/js/branch_form.js"}

doc_events = {
	"Branch": {"validate": "krl_hse.utils.branch.validate_branch"},
}

# doc_events_example = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"krl_hse.tasks.all"
# 	],
# 	"daily": [
# 		"krl_hse.tasks.daily"
# 	],
# 	"hourly": [
# 		"krl_hse.tasks.hourly"
# 	],
# 	"weekly": [
# 		"krl_hse.tasks.weekly"
# 	],
# 	"monthly": [
# 		"krl_hse.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "krl_hse.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "krl_hse.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "krl_hse.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "krl_hse.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["krl_hse.utils.before_request"]
# after_request = ["krl_hse.utils.after_request"]

# Job Events
# ----------
# before_job = ["krl_hse.utils.before_job"]
# after_job = ["krl_hse.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"krl_hse.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
