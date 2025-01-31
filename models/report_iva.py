# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
import logging

_logger = logging.getLogger(__name__)
class ArgentinianReportCustomHandlerExtended(models.AbstractModel):
    _inherit = 'l10n_ar.tax.report.handler'

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        move_info_dict = {}
        total_values_dict = {}
        number_keys = ['taxed', 'not_taxed', 'vat_25', 'vat_5', 'vat_10', 'vat_21', 'vat_27', 'vat_per', 'perc_iibb', 'perc_earnings', 'city_tax', 'other_taxes', 'total']
        
        query_list = []
        full_query_params = []
        options_per_col_group = report._split_options_per_column_group(options)
        for column_group_key, column_group_options in options_per_col_group.items():
            query, params = self._build_query(report, column_group_options, column_group_key)
            query_list.append(f"({query})")
            full_query_params += params
            total_values_dict.setdefault(column_group_key, dict.fromkeys(number_keys, 0.0))

        full_query = " UNION ALL ".join(query_list)
        self._cr.execute(full_query, full_query_params)
        results = self._cr.dictfetchall()
        for result in results:
            move_id = result['id']
            column_group_key = result['column_group_key']
            result['date'] = result['date'].strftime("%Y-%m-%d")
            sign = -1.0 if result['tax_type'] == 'sale' else 1.0

            current_move_info = move_info_dict.setdefault(move_id, {})
            current_move_info['line_name'] = result['move_name']
            current_move_info[column_group_key] = result
            
            document_type = result.get('document_type_name', {})
            document_type = document_type.get('es_AR', list(document_type.values())[0] if document_type else '')
            _logger.info(f"Documento: {document_type}")
            currency_name = result.get('currency_name', '')
            currency_rate = result.get('currency_rate', 0.0)
            
            current_move_info['document_type'] = document_type
            current_move_info['currency_rate'] = currency_rate if currency_rate != 0 else 0
            current_move_info['currency_id'] = currency_name

            totals = total_values_dict[column_group_key]
            for key in number_keys:
                result[key] = sign * result[key]
                totals[key] += result[key]

        lines = [
            (0, self._create_report_line(report, options, move_info, move_id, number_keys))
            for move_id, move_info in move_info_dict.items()
        ]
        
        return lines


    def _create_report_line(self, report, options, move_vals, move_id, number_values):
        columns = []
        for column in options['columns']:
            expression_label = column['expression_label']
            
            if expression_label == 'document_type':
                value = move_vals.get('document_type', '')
            elif expression_label == 'currency_rate':
                value = move_vals.get('currency_rate', 0.0)
            elif expression_label == 'currency_id':
                value = move_vals.get('currency_id', '')
            else:
                value = move_vals.get(column['column_group_key'], {}).get(expression_label)

            columns.append(report._build_column_dict(value, column, options=options))

        return {
            'id': report._get_generic_line_id('account.move', move_id),
            'caret_options': 'account.move',
            'name': move_vals['line_name'],
            'columns': columns,
            'level': 2,
        }
