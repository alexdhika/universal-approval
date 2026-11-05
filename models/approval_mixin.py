from odoo import models, fields, api, _
from odoo.tools.safe_eval import safe_eval
from odoo.exceptions import ValidationError, UserError

class UniversalApprovalMixin(models.AbstractModel):
    _name = 'universal_approval.mixin'
    _description = 'Universal Approval Mixin'

    approval_request_ids = fields.One2many(
        'universal_approval.request', 
        'res_id', 
        string='Approval Requests',
        domain=lambda self: [('res_model', '=', self._name)],
        auto_join=True
    )
    
    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'Waiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Approval State', default='draft', copy=False, tracking=True)

    # Field penanda apakah user yang sedang buka form adalah approver yang sedang pending
    is_current_user_approver = fields.Boolean(
        compute='_compute_is_current_user_approver', 
        store=False
    )

    def _compute_is_current_user_approver(self):
        for rec in self:
            # Cek apakah ada request 'pending' atas nama user yang sedang login
            pending_req = rec.approval_request_ids.filtered(
                lambda r: r.user_id == self.env.user and r.state == 'pending'
            )
            rec.is_current_user_approver = bool(pending_req)

    # Field Many2one untuk menampung TEPAT 1 user yang sedang bertugas saat ini
    current_approver_id = fields.Many2one(
        'res.users',
        string='Pending Approver',
        compute='_compute_current_approver_id',
        store=True,  # Disimpan di DB agar bisa dipakai di filter (to_review)
        index=True,
        help='Satu user yang saat ini sedang menunggu gilirannya untuk me-review dokumen ini.'
    )

    show_return_button = fields.Boolean(
        compute='_compute_current_approver_id',
        help='Menampilkan tombol return jika request masih pending.'
    )

    @api.depends(
        'approval_request_ids.state',
        'approval_request_ids.user_id',
        'approval_request_ids.sequence',
        'approval_request_ids.config_line_id',
        'approval_request_ids.config_line_id.show_return_button',
    )
    def _compute_current_approver_id(self):
        for rec in self:
            # Ambil request yang statusnya 'pending'
            pending_requests = rec.approval_request_ids.filtered(lambda r: r.state == 'pending')
            
            if pending_requests:
                # Ambil 1 user dari request pending dengan sequence terendah (level paling depan)
                # .sorted() memastikan kita mengambil yang paling pertama jika ada edge case
                first_pending = pending_requests.sorted(key=lambda r: (r.sequence, r.id))[0]
                rec.current_approver_id = first_pending.user_id
                rec.show_return_button = first_pending.config_line_id.show_return_button
            else:
                rec.current_approver_id = False
                rec.show_return_button = False

    def action_request_approval(self):
        """Mengevaluasi approval rule dan membuat approval request awal.
    
        Additional approver yang ditandai is_additional_approver=True
        tidak dibuat pada tahap awal. Approver tersebut hanya akan
        ditambahkan secara dinamis ketika approver sebelumnya mengizinkannya.
        """
        for rec in self:
    
            ApprovalRequest = self.env['universal_approval.request'].sudo()
    
            # =========================================================
            # 1. AMBIL RULE
            # =========================================================
    
            rules = self.env['universal_approval.config'].sudo().search([
                ('model_id.model', '=', rec._name)
            ], order='sequence asc')
    
            if not rules:
                raise UserError(
                    _("Tidak dapat mengajukan approval! Belum ada aturan "
                    "(Approval Rule) yang dibuat untuk model %s.")
                    % rec._description
                )
    
            # =========================================================
            # 2. CARI RULE YANG MATCH
            # =========================================================
    
            matched_lines = []
    
            for rule in rules:
    
                if not rule.domain or rule.domain == '[]':
                    is_match = True
                else:
                    try:
                        eval_domain = safe_eval(rule.domain)

                        full_domain = [
                            ('id', '=', rec.id)
                        ] + eval_domain

                        is_match = (
                            self.env[rec._name].sudo().search_count(full_domain) > 0
                        )

                    except Exception as e:
                        raise ValidationError(
                            _("Approval Rule '%s' memiliki domain tidak valid:\n%s")
                            % (rule.display_name, str(e))
                        )
    
                if not is_match:
                    continue
    
                lines = rule.approver_line_ids.sorted(
                    key=lambda l: l.sequence
                )
    
                # =====================================================
                # IMPORTANT:
                # Additional approver TIDAK dibuat pada initial request
                # =====================================================
    
                lines = lines.filtered(
                    lambda line: not line.is_additional_approver
                )
    
                for line in lines:
                    matched_lines.append({
                        'line': line,
                        'config': rule,
                    })
    
            if not matched_lines:
                raise UserError(
                    _("Tidak dapat mengajukan approval karena tidak ada "
                    "Approval rule yang sesuai!")
                )
    
            # =========================================================
            # 3. DEDUPLIKASI APPROVER
            # =========================================================
    
            ordered_approvers = []
            seen_users = set()
    
            for item in matched_lines:
    
                line = item['line']
                config = item['config']
    
                user_id = line.user_id.id
    
                if user_id not in seen_users:
    
                    seen_users.add(user_id)
    
                    ordered_approvers.append({
                        'user_id': user_id,
                        'config_ids': [config.id],
                        'config_line_id': line.id,
                        'config_sequence': line.sequence,
                    })
    
                else:
    
                    existing_approver = next(
                        approver
                        for approver in ordered_approvers
                        if approver['user_id'] == user_id
                    )
    
                    if config.id not in existing_approver['config_ids']:
                        existing_approver['config_ids'].append(config.id)
    
            new_user_ids = {
                approver['user_id']
                for approver in ordered_approvers
            }
    
            # =========================================================
            # 4. AMBIL REQUEST EXISTING
            # =========================================================
    
            existing_requests = ApprovalRequest.search([
                ('res_model', '=', rec._name),
                ('res_id', '=', rec.id),
            ])
    
            existing_by_user = {
                request.user_id.id: request
                for request in existing_requests
            }
    
            # =========================================================
            # 5. HAPUS APPROVER YANG SUDAH TIDAK ADA DI CONFIG
            #
            # JANGAN hapus additional approver yang sudah dibuat runtime.
            # =========================================================
    
            requests_to_remove = existing_requests.filtered(
                lambda request:
                    not request.config_line_id.is_additional_approver
                    and request.user_id.id not in new_user_ids
            )
    
            if requests_to_remove:
                requests_to_remove.unlink()
    
            # =========================================================
            # 6. CREATE / UPDATE INITIAL APPROVER
            # =========================================================
    
            for idx, approver in enumerate(ordered_approvers):
    
                user_id = approver['user_id']
                config_ids = approver['config_ids']
                config_line_id = approver['config_line_id']
    
                sequence = (idx + 1) * 10
    
                existing_request = existing_by_user.get(user_id)
    
                if existing_request:
    
                    existing_request.sudo().write({
                        'sequence': sequence,
                        'config_ids': [(6, 0, config_ids)],
                        'config_line_id': config_line_id,
                    })
    
                else:
    
                    ApprovalRequest.create({
                        'res_model': rec._name,
                        'res_id': rec.id,
                        'user_id': user_id,
                        'sequence': sequence,
                        'state': 'waiting',
                        'config_ids': [(6, 0, config_ids)],
                        'config_line_id': config_line_id,
                    })
    
            # =========================================================
            # 7. SORT REQUEST
            # =========================================================
    
            active_requests = ApprovalRequest.search([
                ('res_model', '=', rec._name),
                ('res_id', '=', rec.id),
            ], order='sequence asc')
    
            # =========================================================
            # 8. TENTUKAN PENDING
            # =========================================================
    
            pending_found = False
    
            for request in active_requests:
    
                if request.state == 'approved':
                    continue
    
                if not pending_found:
    
                    request.write({
                        'state': 'pending',
                    })
    
                    pending_found = True
    
                else:
    
                    request.write({
                        'state': 'waiting',
                    })
    
            # =========================================================
            # 9. UPDATE APPROVAL STATE
            # =========================================================
    
            pending_requests = active_requests.filtered(
                lambda request: request.state == 'pending'
            )
            
            if pending_requests:
                rec.sudo().write({'approval_state': 'to_approve'})
            elif active_requests and all(
                request.state == 'approved'
                for request in active_requests
            ):
                rec.sudo().write({'approval_state': 'approved'})
    
            # =========================================================
            # 10. NOTIFY
            # =========================================================
    
            rec._notify_next_approvers()
                

    def _notify_next_approvers(self):
        # kirim email ke user yang berstatus 'pending' dan buat activity untuk mereka
        """
        Fungsi pembantu untuk mengirim email dan activity ke user yang berstatus 'pending'
        """
        
        for rec in self:
            # pending_requests = rec.sudo().approval_request_ids.filtered(lambda r: r.state == 'pending')
            pending_requests = self.env['universal_approval.request'].sudo().search([
                ('res_model', '=', rec._name),
                ('res_id', '=', rec.id),
                ('state', '=', 'pending'),
            ], order='sequence asc', limit=1)
            
            for req in pending_requests:        
                # Ambil template (spesifik atau fallback)
                template = rec._get_approval_email_template()

                if req.user_id.partner_id.email:
                    # 1. Ambil email perusahaan terkait dokumen (dukung Multi-Company)
                    company = getattr(rec, 'company_id', False) or self.env.company
                    company_email = company.email_formatted or self.env.user.company_id.email_formatted
                    if not company_email:
                        raise UserError(_("Email perusahaan belum diatur. Silakan atur email perusahaan di menu Settings > Companies."))

                    if template:
                        # kirim dengan template
                        template.sudo().send_mail(
                            rec.id,  # res_id dokumen (misal PO ID)
                            force_send=False,
                            email_values={
                                'email_to': req.user_id.partner_id.email,
                                'email_from': company_email,
                                'model': rec._name,  # Pastikan model di-override ke model dokumen asli
                                'res_id': rec.id,
                            }
                        )
                    else:
                        # Kirim email sederhana (tanpa template khusus)
                        subject = _("Persetujuan Diperlukan: %s") % rec.display_name

                        url = "%s/web#id=%s&model=%s&view_type=form" % (
                            self.env['ir.config_parameter'].sudo().get_param('web.base.url'),
                            rec.id,
                            rec._name,
                        )

                        body = """
                            <p>Dokumen <b>%s</b> membutuhkan persetujuan (approval) dari Anda.</p>
                            <p>
                                <a href="%s"
                                style="background-color:#875A7B;color:white;padding:10px 20px;
                                        text-decoration:none;border-radius:4px;">
                                    Buka Dokumen
                                </a>
                            </p>
                        """ % (rec.display_name, url)

                        self.env['mail.mail'].sudo().create({
                            'subject': subject,
                            'body_html': body,
                            'email_to': req.user_id.partner_id.email,
                            'email_from': company_email,
                        })


    def action_approve_current_user(self):
        """Mencari request pending milik user saat ini lalu mengeksekusi approve"""
        for rec in self:
            current_request = rec.approval_request_ids.filtered(
                lambda r: r.user_id == self.env.user and r.state == 'pending'
            )
            if current_request:
                return current_request.action_approve()

    def action_return_current_user(self):
        """Mencari request pending milik user saat ini lalu mengeksekusi return"""
        for rec in self:
            current_request = rec.approval_request_ids.filtered(
                lambda r: r.user_id == self.env.user and r.state == 'pending'
            )
            if current_request:
                return current_request.action_return()
                
    def action_reject_current_user(self):
        """Mencari request pending milik user saat ini lalu membuka wizard reject"""
        for rec in self:
            current_request = rec.approval_request_ids.filtered(
                lambda r: r.user_id == self.env.user and r.state == 'pending'
            )
            if current_request:
                return current_request.action_reject()

    # action cancel, hanya bisa dicancel jika belum ada request yang diapprove, jika sudah ada yang approve maka tidak bisa dicancel
    def action_cancel_approval(self):
        for rec in self:
            # Cek apakah ada request yang sudah diapprove
            approved_requests = rec.approval_request_ids.filtered(lambda r: r.state == 'approved')
            if approved_requests:
                raise UserError(_("Tidak dapat membatalkan approval karena sudah ada request yang disetujui."))
            else:
                # Hapus semua request approval yang masih pending atau waiting
                rec.approval_request_ids.filtered(lambda r: r.state in ['pending', 'waiting']).unlink()
                rec.approval_state = 'draft'

    def _notify_final_approval(self):
        """Mengirim email ke user yang ditentukan di config setelah semua level disetujui"""
        for rec in self:
            # Cari konfigurasi untuk model ini
            config = self.env['universal_approval.config'].sudo().search([
                ('model_id.model', '=', rec._name)
            ], limit=1)

            if config:
                # Kirim email ke user yang ditentukan di config
                notify_users = config.approved_notify_user_ids

                if notify_users:
                    for user in notify_users:
                        if user.email:
                            company = getattr(rec, 'company_id', False) or self.env.company
                            company_email = company.email_formatted or self.env.user.company_id.email_formatted
                            if not company_email:
                                raise UserError(_("Email perusahaan belum diatur. Silakan atur email perusahaan di menu Settings > Companies."))
                            
                            # Kirim email sederhana (tanpa template khusus)
                            subject = _("Dokumen %s telah disetujui oleh semua level approver.") % rec.display_name
                            body = _("Dokumen %s telah disetujui oleh semua level approver. Silakan cek dokumen tersebut di sistem.") % rec.display_name
                            self.env['mail.mail'].sudo().create({
                                'subject': subject,
                                'body_html': body,
                                'email_to': user.email,
                                'email_from': company_email,
                            })

                            
    def notify_return_approval(self, user=None):
        """Mengirim email ke user yang dikirim oleh modul inherit"""
        if not user:
            return
        
        for rec in self:
            if user.email:
                company = getattr(rec, 'company_id', False) or self.env.company
                company_email = company.email_formatted or self.env.user.company_id.email_formatted
                if not company_email:
                    raise UserError(_("Email perusahaan belum diatur. Silakan atur email perusahaan di menu Settings > Companies."))
                
                # Kirim email sederhana (tanpa template khusus)
                subject = _("Dokumen %s telah dikembalikan oleh approver.") % rec.display_name
                body = _("Dokumen %s telah dikembalikan oleh approver. Silakan cek dokumen tersebut di sistem.") % rec.display_name
                self.env['mail.mail'].create({
                    'subject': subject,
                    'body_html': body,
                    'email_to': user.email,
                    'email_from': company_email,
                }).send()

                            
    def _notify_rejection(self):
        """Mengirim email ke user yang ditentukan di config setelah ada request yang ditolak"""
        for rec in self:
            # Cari konfigurasi untuk model ini
            config = self.env['universal_approval.config'].sudo().search([
                ('model_id.model', '=', rec._name)
            ], limit=1)

            if config:
                # Kirim email ke user yang ditentukan di config
                notify_users = config.rejected_notify_user_ids
                if notify_users:
                    for user in notify_users:
                        if user.email:
                            company = getattr(rec, 'company_id', False) or self.env.company
                            company_email = company.email_formatted or self.env.user.company_id.email_formatted
                            if not company_email:
                                raise UserError(_("Email perusahaan belum diatur. Silakan atur email perusahaan di menu Settings > Companies."))
                            
                            # Kirim email sederhana (tanpa template khusus)
                            subject = _("Dokumen %s telah ditolak oleh approver.") % rec.display_name
                            body = _("Dokumen %s telah ditolak oleh approver. Silakan cek dokumen tersebut di sistem.") % rec.display_name
                            self.env['mail.mail'].create({
                                'subject': subject,
                                'body_html': body,
                                'email_to': user.email,
                                'email_from': company_email,
                            }).send()

    def _get_approval_email_template(self):
        """Mendapatkan template email untuk notifikasi approval"""
        return False  # Override di model spesifik jika ingin pakai template berbeda
