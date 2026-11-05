from odoo import models, fields, api, _
from odoo.exceptions import UserError

class UniversalApprovalRequest(models.Model):
    _name = 'universal_approval.request'
    _description = 'Approval Request'
    _order = 'sequence, id'

    res_model = fields.Char(string='Resource Model', required=True, index=True)
    res_id = fields.Many2oneReference(string='Resource ID', model_field='res_model', required=True, index=True)
    user_id = fields.Many2one('res.users', string='Approver', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    approve_date = fields.Datetime(string='Approve/Reject Date', readonly=True)
    note = fields.Text(string='Note', readonly=True)
    config_ids = fields.Many2many(
        'universal_approval.config',
        string='Configurations',
        readonly=True,
    )
    config_line_id = fields.Many2one(
        'universal_approval.config_line',
        string='Approval Config Line',
        ondelete='set null',
    )
    
    state = fields.Selection([
        ('waiting', 'Waiting'),   # Belum giliran
        ('pending', 'Pending'),   # Butuh di-approve sekarang
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], default='waiting')

    res_model_name = fields.Char(
        string='Model',
        compute='_compute_res_model_name',
    )
    
    @api.depends('res_model')
    def _compute_res_model_name(self):
        IrModel = self.env['ir.model']
    
        for record in self:
            if record.res_model:
                model = IrModel._get(record.res_model)
                record.res_model_name = model.name if model else record.res_model
            else:
                record.res_model_name = False
                
    def action_approve(self):
        self.ensure_one()
    
        # Hanya request yang sedang pending yang boleh di-approve
        if self.state != 'pending':
            raise UserError(
                _("Approval request ini tidak sedang menunggu approval.")
            )
    
        # Cek apakah approver ini diperbolehkan menambahkan
        # additional approver
        if self.config_line_id.allow_add_additional_approvers:
            
            return {
                'name': _('Add Additional Approvers'),
                'type': 'ir.actions.act_window',
                'res_model': 'universal_approval.additional_approver_wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_approval_request_id': self.id,
                },
            }
    
        # Tidak boleh menambahkan additional approver
        return self._do_approve()

    def _do_approve(self, additional_config_lines=None):
        self.ensure_one()
    
        req = self

        ApprovalRequest = self.env['universal_approval.request']
    
        # =========================================================
        # 1. APPROVE REQUEST INI
        # =========================================================
    
        req.sudo().write({
            'state': 'approved',
            'approve_date': fields.Datetime.now(),
            'note': 'Approved by %s' % self.env.user.name,
        })
    
        # =========================================================
        # 2. TAMBAHKAN ADDITIONAL APPROVER
        # =========================================================
    
        if additional_config_lines:
    
            existing_requests = ApprovalRequest.sudo().search([
                ('res_model', '=', req.res_model),
                ('res_id', '=', req.res_id),
            ])
    
            existing_user_ids = set(
                existing_requests.mapped('user_id').ids
            )
    
            for config_line in additional_config_lines:
    
                user_id = config_line.user_id.id
    
                # Jangan buat duplicate approver
                if user_id in existing_user_ids:
                    continue
    
                ApprovalRequest.sudo().create({
                    'res_model': req.res_model,
                    'res_id': req.res_id,
                    'user_id': user_id,
                    'sequence': config_line.sequence,
                    'state': 'waiting',
                    'config_ids': [
                        (6, 0, config_line.config_id.ids)
                    ],
                    'config_line_id': config_line.id,
                })
    
                existing_user_ids.add(user_id)
    
        # =========================================================
        # 3. CARI SEMUA REQUEST
        # =========================================================
    
        all_requests = ApprovalRequest.sudo().search([
            ('res_model', '=', req.res_model),
            ('res_id', '=', req.res_id),
        ])
    
        # =========================================================
        # 4. CEK APAKAH LEVEL SAAT INI SUDAH SELESAI
        # =========================================================
    
        same_level_pending = all_requests.filtered(
            lambda r:
                r.sequence == req.sequence
                and r.state not in ('approved', 'rejected')
        )
    
        if not same_level_pending:
    
            # =====================================================
            # 5. CARI LEVEL BERIKUTNYA
            # =====================================================
    
            waiting_requests = all_requests.filtered(
                lambda r: r.state == 'waiting'
            )
    
            if waiting_requests:
    
                next_sequence = min(
                    waiting_requests.mapped('sequence')
                )
    
                next_level_requests = waiting_requests.filtered(
                    lambda r: r.sequence == next_sequence
                )
    
                next_level_requests.sudo().write({
                    'state': 'pending'
                })
    
                target_record = self.env[req.res_model].sudo().browse(
                    req.res_id
                )
    
                target_record._notify_next_approvers()
    
            else:
    
                # =================================================
                # 6. SEMUA APPROVER SUDAH SELESAI
                # =================================================
    
                target_record = self.env[req.res_model].sudo().browse(
                    req.res_id
                )
    
                target_record.approval_state = 'approved'
    
                target_record._notify_final_approval()

    def action_return(self):
        self.ensure_one()
        self.approve_date = fields.Datetime.now()
        self.note = 'Returned by %s' % self.env.user.name
        target_record = self.env[self.res_model].browse(self.res_id)
        target_record.approval_state = 'draft'
        # kirim notifikasi ke user yang ditentukan di config
        # target_record._notify_return_approval()
        
    def action_reject(self):
        # panggil wizard untuk input note
        return {
            'name': 'Reject Approval',
            'type': 'ir.actions.act_window',
            'res_model': 'universal_approval.reject_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.res_id,
                'active_model': self.res_model,
            },
        }

    def open_document(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Document',
            'res_model': self.res_model,
            'view_mode': 'form',
            'res_id': self.res_id,
            'target': 'current',
        }

    def action_edit_note(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit Note'),
            'res_model': 'universal_approval.edit_note_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_approval_request_id': self.id,
                'default_note': self.note,
            },
        }

    def _after_note_updated(self):
        self.ensure_one()

        record = self.env[self.res_model].browse(self.res_id)

        if hasattr(record, '_after_approval_note_updated'):
            record._after_approval_note_updated(self)