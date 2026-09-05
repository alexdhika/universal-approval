from odoo import models, fields, api

class UniversalApprovalRequest(models.Model):
    _name = 'universal_approval.request'
    _description = 'Approval Request'
    _order = 'sequence, id'

    res_model = fields.Char(string='Resource Model', required=True, index=True)
    res_id = fields.Many2oneReference(string='Resource ID', model_field='res_model', required=True, index=True)
    user_id = fields.Many2one('res.users', string='Approver', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    approve_date = fields.Datetime(string='Approve/Reject Date', readonly=True)
    note = fields.Text(string='Note')
    
    state = fields.Selection([
        ('waiting', 'Waiting'),   # Belum giliran
        ('pending', 'Pending'),   # Butuh di-approve sekarang
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], default='waiting')

    def action_approve(self):
        for req in self:
            req.state = 'approved'
            req.approve_date = fields.Datetime.now()
            req.note = 'Approved by %s' % self.env.user.name
            # Cari seluruh request untuk dokumen yang sama
            all_requests = self.search([
                ('res_model', '=', req.res_model),
                ('res_id', '=', req.res_id)
            ])
            
            # 1. Cek apakah masih ada request lain di sequence/level yang sama yang belum approved
            same_level_pending = all_requests.filtered(
                lambda r: r.sequence == req.sequence and r.state != 'approved'
            )
            
            # 2. Jika level saat ini SUDAH LENGKAP di-approve semua
            if not same_level_pending:
                # Cari sequence berikutnya yang masih 'waiting'
                waiting_requests = all_requests.filtered(lambda r: r.state == 'waiting')
                
                if waiting_requests:
                    # Ambil sequence paling kecil dari level yang sedang menunggu
                    next_sequence = min(waiting_requests.mapped('sequence'))
                    next_level_requests = waiting_requests.filtered(lambda r: r.sequence == next_sequence)
                    
                    # Ubah status level berikutnya menjadi 'pending'
                    next_level_requests.write({'state': 'pending'})
                    
                    # Triggers notifikasi ke approver level berikutnya
                    target_record = self.env[req.res_model].browse(req.res_id)
                    target_record._notify_next_approvers()
                else:
                    # Jika tidak ada lagi yang 'waiting', berarti SELURUH LEVEL SUDAH APPROVED
                    target_record = self.env[req.res_model].browse(req.res_id)
                    target_record.approval_state = 'approved'
                    # kirim notifikasi ke user yang ditentukan di config
                    target_record._notify_final_approval()

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
        
class UniversalRejectWizard(models.TransientModel):
    _name = 'universal_approval.reject_wizard'
    _description = 'Reject Wizard'

    note = fields.Text(string='Rejection Note', required=True)

    def action_reject(self):
        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')
        if not active_id or not active_model:
            raise UserError(_("No active record found for rejection."))

        # Cari request yang sedang 'pending' untuk user yang sedang login
        pending_request = self.env['universal_approval.request'].search([
            ('res_model', '=', active_model),
            ('res_id', '=', active_id),
            ('user_id', '=', self.env.user.id),
            ('state', '=', 'pending')
        ], limit=1)

        if not pending_request:
            raise UserError(_("You do not have a pending approval request for this record."))

        # Update status request menjadi 'rejected'
        pending_request.state = 'rejected'
        pending_request.approve_date = fields.Datetime.now()
        pending_request.note = self.note

        # Update status dokumen menjadi 'rejected'
        target_record = self.env[active_model].browse(active_id)
        target_record.approval_state = 'rejected'
        target_record._notify_rejection()