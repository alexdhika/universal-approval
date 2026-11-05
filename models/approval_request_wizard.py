from odoo import models, fields, api, _
from odoo.exceptions import UserError

class UniversalRejectWizard(models.TransientModel):
    _name = 'universal_approval.reject_wizard'
    _description = 'Reject Wizard'

    note = fields.Text(string='Rejection Note', required=True)

    def action_reject(self):
        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')
    
        if not active_id or not active_model:
            raise UserError(_("No active record found for rejection."))
    
        # Cari request yang sedang pending untuk user yang sedang login
        pending_request = self.env['universal_approval.request'].search([
            ('res_model', '=', active_model),
            ('res_id', '=', active_id),
            ('user_id', '=', self.env.user.id),
            ('state', '=', 'pending')
        ], limit=1)
    
        if not pending_request:
            raise UserError(
                _("You do not have a pending approval request for this record.")
            )
    
        # =========================================================
        # 1. AMBIL REJECT BEHAVIOR DARI CONFIG
        # =========================================================
    
        configs = pending_request.config_ids
        
        if not configs:
            reject_behavior = 'stop'
        else:
            reject_behaviors = configs.mapped('reject_behavior')
        
            if len(set(reject_behaviors)) > 1:
                raise UserError(
                    _("Configuration yang terkait dengan approver ini "
                      "memiliki Reject Behavior yang berbeda.")
                )
        
            reject_behavior = reject_behaviors[0] or 'stop'
    
        # =========================================================
        # 2. UPDATE REQUEST YANG MELAKUKAN REJECT
        # =========================================================
    
        pending_request.write({
            'state': 'rejected',
            'approve_date': fields.Datetime.now(),
            'note': self.note,
        })
    
        target_record = self.env[active_model].browse(active_id)
    
        # =========================================================
        # 3. TENTUKAN PERILAKU SETELAH REJECT
        # =========================================================
    
        if reject_behavior == 'stop':
    
            # -----------------------------------------------------
            # STOP APPROVAL
            # Dokumen menjadi rejected
            # Approval yang sudah approved tetap menjadi history
            # -----------------------------------------------------
    
            target_record.approval_state = 'rejected'
    
        elif reject_behavior == 'restart':
    
            # -----------------------------------------------------
            # RESTART APPROVAL
            # Dokumen kembali draft
            # Semua approval diulang
            # -----------------------------------------------------
    
            approval_requests = self.env['universal_approval.request'].search([
                ('res_model', '=', active_model),
                ('res_id', '=', active_id),
            ])
    
            approval_requests.write({
                'state': 'waiting',
            })
    
            target_record.approval_state = 'draft'
    
        elif reject_behavior == 'resume':
    
            # -----------------------------------------------------
            # RESUME APPROVAL
            # Dokumen kembali draft
            # Approval yang sudah approved dipertahankan
            # Approval selain approved dikembalikan ke waiting
            # -----------------------------------------------------
    
            approval_requests = self.env['universal_approval.request'].search([
                ('res_model', '=', active_model),
                ('res_id', '=', active_id),
                ('state', '!=', 'approved'),
            ])
    
            approval_requests.write({
                'state': 'waiting',
            })
    
            target_record.approval_state = 'draft'
    
        else:
            raise UserError(
                _("Reject Behavior tidak valid.")
            )
    
        # =========================================================
        # 4. NOTIFICATION
        # =========================================================
    
        target_record._notify_rejection()
        
    def action_reject_lama(self):
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

class UniversalEditNoteWizard(models.TransientModel):
    _name = 'universal_approval.edit_note_wizard'
    _description = 'Edit Approval Note'

    approval_request_id = fields.Many2one(
        'universal_approval.request',
        required=True,
        readonly=True,
    )

    note = fields.Text()

    def action_save(self):
        self.ensure_one()

        approval = self.approval_request_id

        # SAVE NOTE
        approval.note = self.note

        # AFTER SAVE
        approval._after_note_updated()

        return {'type': 'ir.actions.act_window_close'}

class UniversalAdditionalApproverWizard(models.TransientModel):
    _name = 'universal_approval.additional_approver_wizard'
    _description = 'Add Additional Approvers'

    approval_request_id = fields.Many2one(
        'universal_approval.request',
        string='Approval Request',
        required=True,
        readonly=True,
    )
    
    additional_config_line_ids = fields.Many2many(
        'universal_approval.config_line',
        'ua_additional_approver_config_line_rel',
        'wizard_id',
        'config_line_id',
        string='Additional Approvers',
    )

    @api.onchange('approval_request_id')
    def _onchange_approval_request_id(self):
        for wizard in self:
            if not wizard.approval_request_id:
                wizard.additional_config_line_ids = False
                continue

            config_lines = wizard.approval_request_id.config_ids.mapped(
                'approver_line_ids'
            ).filtered(
                lambda line: line.is_additional_approver
            )

            wizard.additional_config_line_ids = [
                (6, 0, config_lines.ids)
            ]

    available_additional_config_line_ids = fields.Many2many(
        'universal_approval.config_line',
        compute='_compute_available_additional_config_line_ids',
    )

    @api.depends('approval_request_id')
    def _compute_available_additional_config_line_ids(self):
        for wizard in self:
            if wizard.approval_request_id:
                wizard.available_additional_config_line_ids = (
                    wizard.approval_request_id.config_ids
                    .mapped('approver_line_ids')
                    .filtered(lambda line: line.is_additional_approver)
                )
            else:
                wizard.available_additional_config_line_ids = False

    def action_approve_without_add(self):
        self.ensure_one()
    
        approval = self.approval_request_id
    
        if approval.state != 'pending':
            raise UserError(
                _("Approval request ini sudah tidak pending.")
            )
    
        return approval._do_approve()
        
    def action_add_and_approve(self):
        self.ensure_one()

        approval = self.approval_request_id

        if approval.state != 'pending':
            raise UserError(
                _("Approval request ini sudah tidak pending.")
            )

        selected_lines = self.additional_config_line_ids

        # Pastikan hanya additional approver yang boleh dipilih
        invalid_lines = selected_lines.filtered(
            lambda line: not line.is_additional_approver
        )

        if invalid_lines:
            raise UserError(
                _("Approver yang dipilih bukan additional approver.")
            )

        approval._do_approve(
            additional_config_lines=selected_lines
        )

        return {'type': 'ir.actions.act_window_close'}