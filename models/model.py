# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo.tools import float_is_zero, float_compare
from odoo import models, fields, api


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
