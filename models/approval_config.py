from odoo import models, fields, api
from odoo.exceptions import UserError

class UniversalApprovalConfig(models.Model):
    _name = 'universal_approval.config'
    _description = 'Universal Approval Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Rule Name', required=True)
    model_id = fields.Many2one(
        'ir.model', 
        string='Target Model', 
        required=True,
        ondelete='cascade',
        tracking=True
    )
    model_name = fields.Char(related='model_id.model', store=True)
    domain = fields.Char(string='Filter Domain', default='[]', tracking=True, help="Filter domain untuk menentukan record yang akan menggunakan rule ini. Contoh: [('state', '=', 'draft')]")
    sequence = fields.Integer(string='Sequence Rule', default=10, tracking=True, help="Urutan rule jika ada beberapa rule untuk model yang sama. Rule dengan sequence lebih kecil akan dievaluasi lebih dulu.")

    tag_ids = fields.Many2many(
            'universal_approval.config_tag',
            string='Tags',
            ondelete='restrict'
        )

    # Ganti Many2many menjadi One2many ke model line
    approver_line_ids = fields.One2many(
        'universal_approval.config_line', 
        'config_id', 
        string='Approver Levels',
        tracking=True,
        copy=True,
        help="Daftar approver untuk setiap level. Urutan level ditentukan oleh field 'Level / Step'."
    )

    # Computed field untuk menampung ID ir.model yang valid
    allowed_model_ids = fields.Many2many(
        'ir.model',
        compute='_compute_allowed_model_ids',
        string='Allowed Models'
    )

    # tambahkan field untuk list user yang dikirim notifikasi
    # setelah semua approve dan juga rejected
    approved_notify_user_ids = fields.Many2many(
        'res.users',
        'approval_config_approved_user_rel',  # Nama tabel perantara 1
        'config_id',                          # Column 1 (FK ke model ini)
        'user_id',
        string='Notify Users After Approved',
        tracking=True,
        help="Daftar user yang akan dikirim notifikasi setelah semua level approver menyetujui dokumen."
    )

    rejected_notify_user_ids = fields.Many2many(
        'res.users',
        'approval_config_rejected_user_rel',  # Nama tabel perantara 2 (harus beda!)
        'config_id',                          # Column 1
        'user_id',
        tracking=True,
        string='Notify Users After Rejection',
        help="Daftar user yang akan dikirim notifikasi setelah dokumen ditolak oleh semua level approver."
    )

    @api.depends()
    def _compute_allowed_model_ids(self):
        """
        Mengambil semua model terdaftar di registry Odoo yang meng-inherit 
        'universal_approval.mixin'.
        """
        # Pastikan nama di bawah SAMA PERSIS dengan _name di class UniversalApprovalMixin
        mixin_name = 'universal_approval.mixin' 
        inherited_model_names = []

        # Loop seluruh model yang aktif di registry Odoo
        for model_name, model_obj in self.env.items():
            # Skip AbstractModel dan TransientModel jika tidak ingin ditampilkan di config
            if model_obj._abstract or model_obj._transient:
                continue

            # Check apakah mixin_name ada dalam hirarki _parents atau _inherit model tersebut
            parents = getattr(model_obj, '_parents', set())
            direct_inherits = getattr(model_obj, '_inherit', [])

            if isinstance(direct_inherits, str):
                direct_inherits = [direct_inherits]

            if mixin_name in parents or mixin_name in direct_inherits:
                inherited_model_names.append(model_name)

        # Cari ID dari ir.model berdasarkan list nama teknis model yang ditemukan
        allowed_models = self.env['ir.model'].search([('model', 'in', inherited_model_names)])
        
        for rec in self:
            rec.allowed_model_ids = allowed_models
            
    @api.depends()
    def _compute_allowed_model_ids1(self):
        """
        Mengambil semua model terdaftar di registry Odoo yang memiliki 
        'universal.approval.mixin' dalam atribut _inherit / _parents.
        """
        mixin_name = 'universal_approval.mixin'
        inherited_model_names = []

        # Loop seluruh model yang sedang aktif ter-load di registry Odoo
        for model_name, model_obj in self.env.items():
            # Cek apakah mixin ada di dalam _inherit model tersebut
            parents = getattr(model_obj, '_inherit', [])
            if isinstance(parents, str):
                parents = [parents]
            
            if parents and mixin_name in parents:
                inherited_model_names.append(model_name)

        # Cari ID dari ir.model berdasarkan nama-nama model teknis yang ditemukan
        allowed_models = self.env['ir.model'].search([('model', 'in', inherited_model_names)])
        
        for rec in self:
            rec.allowed_model_ids = allowed_models

    def tes_cek_inherit_model(self):
        """
        Fungsi ini untuk testing/debugging, menampilkan semua model yang meng-inherit universal_approval.mixin.
        """
        # ambil semua record dari model ir.model
        all_models = self.env['ir.model'].search([])
        cek_inherit = []
        for model in all_models:
            model_name = model.model
            model_obj = self.env[model_name]
            parents = getattr(model_obj, '_parents', [])
            if model.id == 643:
                raise UserError(f"Model: {model_name}, _parents: {parents}")

class ApprovalConfigLine(models.Model):
    _name = 'universal_approval.config_line'
    _description = 'Universal Approval Configuration Line'
    _order = 'sequence, id'  # Mengurutkan otomatis berdasarkan sequence

    config_id = fields.Many2one('universal_approval.config', string='Universal Approval Config', ondelete='cascade')
    sequence = fields.Integer(string='Level / Step', default=10)
    user_id = fields.Many2one('res.users', string='Approver', required=True)
    
    # Opsi Tambahan: Boleh berbentuk Role/Group alih-alih spesifik 1 User
    # group_id = fields.Many2one('res.groups', string='Approver Group')

class ApprovalConfigTag(models.Model):
    _name = 'universal_approval.config_tag'

    name = fields.Char(string='Tag', required=True)