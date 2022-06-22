# -*- coding: utf-8 -*-
import ast
import pytz
from datetime import datetime
from collections import defaultdict
from odoo.tools import float_is_zero, float_compare
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo import models, fields, api


class AccountMove(models.Model):

    _inherit = 'account.move'

    def convert_datetime(self, datetm):
        display_date_result = ''
        if datetm:
            user_tz = self.env.user.tz or pytz.utc
            local = pytz.timezone(user_tz)
            if type(datetm) is datetime:
                display_date_result = datetime.strftime(pytz.utc.localize(datetm).astimezone(local),"%m/%d/%Y %H:%M:%S")
            else:
                display_date_result = datetime.strftime(pytz.utc.localize(datetime.strptime(datetm, DEFAULT_SERVER_DATETIME_FORMAT)).astimezone(local),"%m/%d/%Y %H:%M:%S")
        return display_date_result

    date_with_time = fields.Datetime(string='Accounting Date with hour')

    @api.model
    def create(self, vals):
        res = super(AccountMove, self).create(vals)
        if res.move_type == 'entry' or res.move_type == 'out_invoice':
            if not res.date_with_time:
                res.date_with_time = datetime.now()
        return res


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    pos_order_id = fields.Many2one('pos.order', string='POS Order')
    pos_reference = fields.Char(
        string='POS Receipt Number', store=True, related='pos_order_id.pos_reference')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    pos_order_id = fields.Many2one('pos.order', string='POS Order')
    pos_reference = fields.Char(
        string='POS Receipt Number', store=True, related='pos_order_id.pos_reference')
    date_with_time = fields.Datetime(string='Accounting Date with hour', related='move_id.date_with_time', store=True, copy=False)

    @api.model
    def _query_get(self, domain=None):
        self.check_access_rights('read')

        context = dict(self._context or {})
        domain = domain or []
        if not isinstance(domain, (list, tuple)):
            domain = ast.literal_eval(domain)

        date_field = 'date'
        if context.get('datetime_field'):
            date_field = 'date_with_time'
        if context.get('aged_balance'):
            date_field = 'date_maturity'
        if context.get('date_to'):
            domain += [(date_field, '<=', context['date_to'])]
        if context.get('date_from'):
            if not context.get('strict_range'):
                domain += ['|', (date_field, '>=', context['date_from']), ('account_id.user_type_id.include_initial_balance', '=', True)]
            elif context.get('initial_bal'):
                domain += [(date_field, '<', context['date_from'])]
            else:
                domain += [(date_field, '>=', context['date_from'])]

        if context.get('journal_ids'):
            domain += [('journal_id', 'in', context['journal_ids'])]

        state = context.get('state')
        if state and state.lower() != 'all':
            domain += [('move_id.state', '=', state)]

        if context.get('company_id'):
            domain += [('company_id', '=', context['company_id'])]
        elif context.get('allowed_company_ids'):
            domain += [('company_id', 'in', self.env.companies.ids)]
        else:
            domain += [('company_id', '=', self.env.company.id)]

        if context.get('reconcile_date'):
            domain += ['|', ('reconciled', '=', False), '|', ('matched_debit_ids.max_date', '>', context['reconcile_date']), ('matched_credit_ids.max_date', '>', context['reconcile_date'])]

        if context.get('account_tag_ids'):
            domain += [('account_id.tag_ids', 'in', context['account_tag_ids'].ids)]

        if context.get('account_ids'):
            domain += [('account_id', 'in', context['account_ids'].ids)]

        if context.get('analytic_tag_ids'):
            domain += [('analytic_tag_ids', 'in', context['analytic_tag_ids'].ids)]

        if context.get('analytic_account_ids'):
            domain += [('analytic_account_id', 'in', context['analytic_account_ids'].ids)]

        if context.get('partner_ids'):
            domain += [('partner_id', 'in', context['partner_ids'].ids)]

        if context.get('partner_categories'):
            domain += [('partner_id.category_id', 'in', context['partner_categories'].ids)]

        where_clause = ""
        where_clause_params = []
        tables = ''
        if domain:
            domain.append(('display_type', 'not in', ('line_section', 'line_note')))
            domain.append(('move_id.state', '!=', 'cancel'))
            query = self._where_calc(domain)

            # Wrap the query with 'company_id IN (...)' to avoid bypassing company access rights.
            self._apply_ir_rules(query)

            tables, where_clause, where_clause_params = query.get_sql()
        return tables, where_clause, where_clause_params


class PosSession(models.Model):

    _inherit = 'pos.session'

    def _create_cash_statement_lines_and_cash_move_lines(self, data):
        # Create the split and combine cash statement lines and account move lines.
        # Keep the reference by statement for reconciliation.
        # `split_cash_statement_lines` maps `statement` -> split cash statement lines
        # `combine_cash_statement_lines` maps `statement` -> combine cash statement lines
        # `split_cash_receivable_lines` maps `statement` -> split cash receivable lines
        # `combine_cash_receivable_lines` maps `statement` -> combine cash receivable lines
        MoveLine = data.get('MoveLine')
        split_receivables_cash = data.get('split_receivables_cash')
        combine_receivables_cash = data.get('combine_receivables_cash')

        statements_by_journal_id = {statement.journal_id.id: statement for statement in self.statement_ids}
        # handle split cash payments
        split_cash_statement_line_vals = defaultdict(list)
        split_cash_receivable_vals = defaultdict(list)
        for payment, amounts in split_receivables_cash.items():
            statement = statements_by_journal_id[payment.payment_method_id.cash_journal_id.id]
            split_cash_statement_line_vals[statement].append(self._get_statement_line_vals(statement, payment.payment_method_id.receivable_account_id, amounts['amount'], date=payment.payment_date, partner=payment.pos_order_id.partner_id, payment=payment))
            split_cash_receivable_vals[statement].append(self._get_split_receivable_vals(payment, amounts['amount'], amounts['amount_converted']))
        # handle combine cash payments
        combine_cash_statement_line_vals = defaultdict(list)
        combine_cash_receivable_vals = defaultdict(list)
        for payment_method, amounts in combine_receivables_cash.items():
            if not float_is_zero(amounts['amount'] , precision_rounding=self.currency_id.rounding):
                statement = statements_by_journal_id[payment_method.cash_journal_id.id]
                combine_cash_statement_line_vals[statement].append(self._get_statement_line_vals(statement, payment_method.receivable_account_id, amounts['amount']))
                combine_cash_receivable_vals[statement].append(self._get_combine_receivable_vals(payment_method, amounts['amount'], amounts['amount_converted']))
        # create the statement lines and account move lines
        BankStatementLine = self.env['account.bank.statement.line']
        split_cash_statement_lines = {}
        combine_cash_statement_lines = {}
        split_cash_receivable_lines = {}
        combine_cash_receivable_lines = {}
        for statement in self.statement_ids:
            split_cash_statement_lines[statement] = BankStatementLine.create(split_cash_statement_line_vals[statement])

            for l in split_cash_statement_lines[statement]:
                if l.move_id:
                    for m_l in l.move_id.line_ids:
                        m_l.write({'pos_order_id': l.pos_order_id and l.pos_order_id.id or False})

            combine_cash_statement_lines[statement] = BankStatementLine.create(combine_cash_statement_line_vals[statement])
            split_cash_receivable_lines[statement] = MoveLine.create(split_cash_receivable_vals[statement])
            combine_cash_receivable_lines[statement] = MoveLine.create(combine_cash_receivable_vals[statement])

        data.update(
            {'split_cash_statement_lines':    split_cash_statement_lines,
             'combine_cash_statement_lines':  combine_cash_statement_lines,
             'split_cash_receivable_lines':   split_cash_receivable_lines,
             'combine_cash_receivable_lines': combine_cash_receivable_lines
             })
        return data

    def _get_split_receivable_vals(self, payment, amount, amount_converted):
        pos_order_id = False
        if payment and payment.pos_order_id:
            pos_order_id = payment.pos_order_id.id
        partial_vals = {
            'account_id': payment.payment_method_id.receivable_account_id.id,
            'move_id': self.move_id.id,
            'partner_id': self.env["res.partner"]._find_accounting_partner(payment.partner_id).id,
            'name': '%s - %s' % (self.name, payment.payment_method_id.name),
            'pos_order_id': pos_order_id,
        }
        return self._debit_amounts(partial_vals, amount, amount_converted)

    def _get_statement_line_vals(self, statement, receivable_account, amount, date=False, partner=False, payment=False):
        pos_order_id = False
        if payment and payment.pos_order_id:
            pos_order_id = payment.pos_order_id.id
        vals = {
            'date': fields.Date.context_today(self, timestamp=date),
            'amount': amount,
            'payment_ref': self.name,
            'statement_id': statement.id,
            'journal_id': statement.journal_id.id,
            'counterpart_account_id': receivable_account.id,
            'partner_id': partner and self.env["res.partner"]._find_accounting_partner(partner).id,
            'pos_order_id': pos_order_id,
        }
        return vals
