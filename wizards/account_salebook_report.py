# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from datetime import date
from datetime import datetime


class AccountSaleBookReport(models.TransientModel):
    _name = "account.salebook.report"
    _description = "Sale Book Report"

    def _get_default_account_ids(self):
        journals = self.env['account.journal'].search([('type', '=', 'sale')])
        accounts_sale = self.env['account.account'].search([('user_type_id', '=', 'Income'),('deprecated', '=', False)])
        cash_journal = self.env['account.journal'].search([('type', '=', 'cash')])
        accounts = []
        for journal in journals:
            accounts.append(journal.default_account_id.id)
        for acc in accounts_sale:
            accounts.append(acc.id)
        for cash in cash_journal:
            accounts.append(cash.default_account_id.id)
        return accounts

    date_from = fields.Datetime(string='Start Date', default=datetime.now(), required=True)
    date_to = fields.Datetime(string='End Date', default=datetime.now(), required=True)
    target_move = fields.Selection([('posted', 'Posted Entries'),
                                    ('all', 'All Entries')], string='Target Moves', required=True,
                                   default='posted')
    journal_ids = fields.Many2many('account.journal', string='Journals', required=True,
                                   default=lambda self: self.env['account.journal'].search([]))
    account_ids = fields.Many2many('account.account', 'account_account_salebook_report', 'report_line_id',
                                   'account_id', 'Accounts', default=_get_default_account_ids)

    display_account = fields.Selection(
        [('all', 'All'), ('movement', 'With movements'),
         ('not_zero', 'With balance is not equal to 0')],
        string='Display Accounts', required=True, default='movement')
    sortby = fields.Selection(
        [('sort_date', 'Date'), ('sort_journal_partner', 'Journal & Partner')],
        string='Sort by',
        required=True, default='sort_date')
    initial_balance = fields.Boolean(string='Include Initial Balances',
                                     help='If you selected date, this field allow you to add a row to display the amount of debit/credit/balance that precedes the filter you\'ve set.')
    create_user_id = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user)
    create_user_id_m2m = fields.Many2many('res.users', string='Created By', default=lambda self: self.env.user)

    @api.onchange('account_ids')
    def onchange_account_ids(self):
        if self.account_ids:
            journals = self.env['account.journal'].search([('type', '=', 'sale')])
            cash_journal = self.env['account.journal'].search([('type', '=', 'cash')])
            accounts_sale = self.env['account.account'].search([('user_type_id', '=', 'Income'),('deprecated', '=', False)])
            accounts = []
            for journal in journals:
                accounts.append(journal.payment_credit_account_id.id)
            for acc in accounts_sale:
                accounts.append(acc.id) 
            for cash in cash_journal:
                accounts.append(cash.default_account_id.id)
            domain = {'account_ids': [('id', 'in', accounts)]}
            return {'domain': domain}


    def _build_comparison_context(self, data):
        result = {}
        result['journal_ids'] = 'journal_ids' in data['form'] and data['form'][
            'journal_ids'] or False
        result['state'] = 'target_move' in data['form'] and data['form'][
            'target_move'] or ''
        result['date_from'] = data['form']['date_from'] or False
        result['date_to'] = data['form']['date_to'] or False
        result['strict_range'] = True if result['date_from'] else False
        result['create_user_id'] = self.create_user_id and self.create_user_id.id or False
        return result

    def check_report(self):
        data = {}
        data['form'] = self.read(['target_move', 'date_from', 'date_to', 'journal_ids', 'account_ids','sortby', 'initial_balance', 'display_account'])[0]
        comparison_context = self._build_comparison_context(data)
        data['form']['comparison_context'] = comparison_context
        return self.env.ref(
            'om_account_daily_reports.action_report_sale_book').report_action(self,
                                                                     data=data)

