from frappe import _

def get_data():
    return [
        {
            "module_name": "Dopplermap Health",
            "category": "Modules",
            "label": _("Dopplermap Health"),
            "icon": "fa fa-stethoscope",
            "type": "module",
            "app": "dopplermap_app"
        }
    ]