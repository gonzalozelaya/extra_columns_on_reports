# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging


_logger = logging.getLogger(__name__)
class PartnerLedgerUSD(models.AbstractModel):
    _inherit = 'account.partner.ledger.report.handler'

    def _get_aml_values(self, options, partner_ids, offset=0, limit=None):
        rslt = super()._get_aml_values(options, partner_ids, offset, limit)
        
        # Agregar balance en USD sumando todas las líneas de amount_currency de forma acumulativa
        for partner_id, aml_results in rslt.items():
            balance_usd = 0.0  # Inicializamos el balance en USD acumulado
            
            for aml in aml_results:
                currency = self.env['res.currency'].browse(aml.get('currency_id'))
                if currency and currency.name == 'USD':  # Solo acumulamos si es USD
                    balance_usd += aml.get('amount_currency', 0.0)  # Acumulamos el balance
                    _logger.info(f"Balance: {balance_usd}" )
                aml['balance_usd'] = balance_usd  # Asignamos el balance acumulado a la línea
        
        return rslt
    
    def _get_report_line_move_line(self, options, aml_query_result, partner_line_id, init_bal_by_col_group, level_shift=0):
        report_line = super()._get_report_line_move_line(options, aml_query_result, partner_line_id, init_bal_by_col_group, level_shift)
        
        # Obtener el balance acumulado de USD
        if 'balance_usd' not in init_bal_by_col_group:
            init_bal_by_col_group['balance_usd'] = 0.0
            
        balance_usd = aml_query_result.get('balance_usd', 0.0)
        _logger.info(f"Updated Balance USD: {balance_usd}")
        
        # Sumar el balance actual en USD a la acumulación
        #init_bal_by_col_group['balance_usd'] += aml_query_result.get('amount_currency', 0.0)
        #balance_usd = init_bal_by_col_group['balance_usd']
        # Obtener el balance acumulado en USD desde aml_query_result

        
        
        # Asegurar que el formato de moneda es USD
        usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        _logger.info(f"Currency: {usd_currency}" )
        # Obtener referencia del reporte
        report = self.env['account.report'].browse(options['report_id'])
        # Obtener referencia del reporte
        report = self.env['account.report'].browse(options['report_id'])
        
        columns = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            col_value = aml_query_result.get(col_expr_label) if column['column_group_key'] == aml_query_result['column_group_key'] else None
            currency = False

            if col_expr_label == 'balance':
                col_value += init_bal_by_col_group[column['column_group_key']]
            elif col_expr_label == 'amount_currency':
                currency = self.env['res.currency'].browse(aml_query_result['currency_id'])
                if currency == self.env.company.currency_id:
                    col_value = ''
            elif col_expr_label == 'balance_usd':
                col_value = balance_usd
                currency = usd_currency
            
            columns.append(report._build_column_dict(col_value, column, options=options, currency=currency))
        
        report_line['columns'] = columns
        # Agregar columna balance en USD con la moneda correcta
        #report_line['columns'].append(report._build_column_dict(balance_usd, None, options=options, currency=usd_currency))
        
        return report_line
    
