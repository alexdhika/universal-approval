{
    'name': "Universal Approval",

    'summary': "Configuration and management of approval requests",

    'description': """
Long description of module's purpose
    """,

    'author': "Surya Semesta Dev Team",
    'website': "https://www.suryasemesta.com",
    'category': 'Uncategorized',
    'version': '0.1',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/res.groups.xml',
        'views/approval_config_views.xml',
        'views/approval_config_category_views.xml',
        'views/approval_config_tag_views.xml',
        'views/approval_request_views.xml',
        'views/approval_request_reject_wizard_views.xml',
        'views/approval_request_edit_note_wizard_views.xml',
        'views/approval_request_additional_approver_views.xml',
        'views/menu_views.xml'
    ],
    'license': 'LGPL-3',
}

