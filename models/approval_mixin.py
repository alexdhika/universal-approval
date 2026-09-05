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
        store=True,  # Disimpan di DB agar bisa dipakai di filter/search bar & performance lebih ringan
        index=True,
        help='Satu user yang saat ini sedang menunggu gilirannya untuk me-review dokumen ini.'
    )

    @api.depends('approval_request_ids.state', 'approval_request_ids.user_id', 'approval_request_ids.sequence')
    def _compute_current_approver_id(self):
        for rec in self:
            # Ambil request yang statusnya 'pending'
            pending_requests = rec.approval_request_ids.filtered(lambda r: r.state == 'pending')
            
            if pending_requests:
                # Ambil 1 user dari request pending dengan sequence terendah (level paling depan)
                # .sorted() memastikan kita mengambil yang paling pertama jika ada edge case
                first_pending = pending_requests.sorted(key=lambda r: (r.sequence, r.id))[0]
                rec.current_approver_id = first_pending.user_id
            else:
                rec.current_approver_id = False

    def action_request_approval1(self):
            """Mengevaluasi rule, mencegah duplikasi approver, dan membuat request approval"""
            for rec in self:
                rules = self.env['universal_approval.config'].search([
                    ('model_id.model', '=', rec._name)
                ], order='sequence asc')

                # Cek jika sama sekali tidak ada konfigurasi rule untuk model ini
                if not rules:
                    raise UserError(
                        _("Tidak dapat mengajukan approval! Belum ada aturan (Approval Rule) yang dibuat untuk model %s.") % rec._description
                    )

                matched_lines = []
                for rule in rules:
                    if not rule.domain or rule.domain == '[]':
                        is_match = True
                    else:
                        eval_domain = safe_eval(rule.domain)
                        full_domain = [('id', '=', rec.id)] + eval_domain
                        is_match = self.env[rec._name].search_count(full_domain) > 0

                    if is_match:
                        lines = rule.approver_line_ids.sorted(key=lambda l: l.sequence)
                        matched_lines.extend(lines)

                if matched_lines:
                    rec.approval_state = 'to_approve'

                    # --- DE-DUPLIKASI APPROVER ---
                    # Menggunakan dictionary untuk memastikan 1 user hanya punya 1 request di sequence terendah/pertamanya
                    unique_approvers = {}
                    for line in matched_lines:
                        user_id = line.user_id.id
                        # Jika user belum ada, atau menemukan sequence yang lebih rendah (lebih awal)
                        if user_id not in unique_approvers or line.sequence < unique_approvers[user_id]:
                            unique_approvers[user_id] = line.sequence

                    # Cari sequence terendah secara keseluruhan untuk menentukan siapa yang 'pending' duluan
                    min_sequence = min(unique_approvers.values())

                    # Buat record approval.request tanpa duplikat
                    for user_id, seq in unique_approvers.items():
                        initial_state = 'pending' if seq == min_sequence else 'waiting'

                        self.env['universal_approval.request'].create({
                            'res_model': rec._name,
                            'res_id': rec.id,
                            'user_id': user_id,
                            'sequence': seq,
                            'state': initial_state,
                        })

                    rec._notify_next_approvers()
                else:
                    rec.approval_state = 'approved'

    def action_request_approval(self):
        """Mengevaluasi rule, mencegah duplikasi approver, dan membuat request approval"""
        for rec in self:
            rules = self.env['universal_approval.config'].search([
                ('model_id.model', '=', rec._name)
            ], order='sequence asc')

            if not rules:
                raise UserError(
                    _("Tidak dapat mengajukan approval! Belum ada aturan (Approval Rule) yang dibuat untuk model %s.") % rec._description
                )

            matched_lines = []
            for rule in rules:
                if not rule.domain or rule.domain == '[]':
                    is_match = True
                else:
                    eval_domain = safe_eval(rule.domain)
                    full_domain = [('id', '=', rec.id)] + eval_domain
                    is_match = self.env[rec._name].search_count(full_domain) > 0

                if is_match:
                    lines = rule.approver_line_ids.sorted(key=lambda l: l.sequence)
                    matched_lines.extend(lines)

            if matched_lines:
                rec.approval_state = 'to_approve'

                # --- DE-DUPLIKASI DAN PENENTUAN URUTAN GLOBAL ---
                # Menggunakan list/dict untuk menjaga urutan pertama kali User muncul (First-Come First-Served)
                ordered_approvers = []
                seen_users = set()

                for line in matched_lines:
                    user_id = line.user_id.id
                    if user_id not in seen_users:
                        seen_users.add(user_id)
                        ordered_approvers.append(user_id)

                # Buat record approval.request berdasarkan urutan antrean global
                # User pertama dalam antrean (index 0) langsung 'pending', sisanya 'waiting'
                for idx, user_id in enumerate(ordered_approvers):
                    global_sequence = (idx + 1) * 10  # Membuat sequence 10, 20, 30, dst.
                    initial_state = 'pending' if idx == 0 else 'waiting'

                    self.env['universal_approval.request'].create({
                        'res_model': rec._name,
                        'res_id': rec.id,
                        'user_id': user_id,
                        'sequence': global_sequence,
                        'state': initial_state,
                    })

                rec._notify_next_approvers()
            else:
                rec.approval_state = 'approved'

    def _get_approval_email_template(self):
        """Mendapatkan template email untuk notifikasi approval"""
        return False  # Override di model spesifik jika ingin pakai template berbeda

    def _notify_next_approvers(self):
        # kirim email ke user yang berstatus 'pending' dan buat activity untuk mereka
        """
        Fungsi pembantu untuk mengirim email dan activity ke user yang berstatus 'pending'
        """
        for rec in self:
            pending_requests = rec.approval_request_ids.filtered(lambda r: r.state == 'pending')
            for req in pending_requests:
                # Buat activity untuk user yang berstatus 'pending'
                # rec.activity_schedule(
                #     'mail.mail_activity_data_todo',
                #     user_id=req.user_id.id,
                #     note=_("Anda memiliki dokumen yang menunggu persetujuan: %s") % rec.display_name
                # )
                
                # raise UserError(rec._name)
                # Kirim email notifikasi (opsional, bisa diatur di template email)
                # template = self.env.ref('universal_approval.email_template_approval_request', raise_if_not_found=False)
                self.ensure_one()
        
                # Ambil template (spesifik atau fallback)
                template = self._get_approval_email_template()

                if template and req.user_id.email:
                    # 1. Ambil email perusahaan terkait dokumen (dukung Multi-Company)
                    company = getattr(rec, 'company_id', False) or self.env.company
                    company_email = company.email_formatted or self.env.user.company_id.email_formatted
                    if not company_email:
                        raise UserError(_("Email perusahaan belum diatur. Silakan atur email perusahaan di menu Settings > Companies."))
                    # Buat string subject secara presisi dari Python

                    target_model = self.env['ir.model'].search([('model', '=', rec._name)], limit=1)
                    # Menggunakan with_context untuk memastikan model & res_id dikirim ke parser QWeb
                    template.send_mail(
                        rec.id,  # res_id dokumen (misal PO ID)
                        force_send=False,
                        email_values={
                            'email_to': req.user_id.email,
                            'email_from': company_email,
                            'model': rec._name,  # Pastikan model di-override ke model dokumen asli
                            'res_id': rec.id,
                        }
                    )

    def action_approve_current_user(self):
        """Mencari request pending milik user saat ini lalu mengeksekusi approve"""
        for rec in self:
            current_request = rec.approval_request_ids.filtered(
                lambda r: r.user_id == self.env.user and r.state == 'pending'
            )
            if current_request:
                current_request.action_approve()

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
            # tolak jika user bukan requestor_id (user yang membuat dokumen)
            if rec.requestor_id != self.env.user:
                raise UserError(_("Hanya user yang membuat dokumen ini yang dapat membatalkan approval."))
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
            config = self.env['universal_approval.config'].search([
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
            config = self.env['universal_approval.config'].search([
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