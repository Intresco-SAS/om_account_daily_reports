# -*- coding: utf-8 -*-

from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    pos_order_id = fields.Many2one('pos.order', string='POS Order')
    pos_reference = fields.Char(string='POS Receipt Number', store=True, related='pos_order_id.pos_reference')


class PosSession(models.Model):

    _inherit = 'pos.session'

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
