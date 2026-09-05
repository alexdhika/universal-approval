{
    'name': "Universal Approval",

    'summary': "Configuration and management of approval requests",

    'description': """
Long description of module's purpose
    """,

    'author': "Surya Semesta Dev Team",
    'website': "https://www.suryasemesta.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'mail'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/approval_config_views.xml',
        'views/approval_config_tag_views.xml',
        'views/approval_request_views.xml',
        'views/menu_views.xml',
        'views/reject_wizard_views.xml',
    ],
    'license': 'LGPL-3',
}

