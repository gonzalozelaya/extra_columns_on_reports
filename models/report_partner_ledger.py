# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from collections import defaultdict

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
                aml['balance_usd'] = balance_usd  # Asignamos el balance acumulado a la línea
        
        return rslt
    
    def _get_report_line_move_line(self, options, aml_query_result, partner_line_id, init_bal_by_col_group, level_shift=0):
        report_line = super()._get_report_line_move_line(options, aml_query_result, partner_line_id, init_bal_by_col_group, level_shift)
        
        # Obtener el balance acumulado de USD
        if 'balance_usd' not in init_bal_by_col_group:
            init_bal_by_col_group['balance_usd'] = 0.0
            
        balance_usd = aml_query_result.get('balance_usd', 0.0)
        
        # Sumar el balance actual en USD a la acumulación
        #init_bal_by_col_group['balance_usd'] += aml_query_result.get('amount_currency', 0.0)
        #balance_usd = init_bal_by_col_group['balance_usd']
        # Obtener el balance acumulado en USD desde aml_query_result

        
        
        # Asegurar que el formato de moneda es USD
        usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
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

    def _get_query_sums(self, options):
        """ Construct a query retrieving all the aggregated sums to build the report. It includes:
        - sums for all partners.
        - sums for the initial balances.
        :param options:             The report options.
        :return:                    (query, params)
        """
        params = []
        queries = []
        report = self.env.ref('account_reports.partner_ledger_report')
    
        # Create the currency table.
        ct_query = report._get_query_currency_table(options)
        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            tables, where_clause, where_params = report._query_get(column_group_options, 'normal')
            params.append(column_group_key)
            params += where_params
            queries.append(f"""
                SELECT
                    account_move_line.partner_id                                                          AS groupby,
                    %s                                                                                    AS column_group_key,
                    SUM(ROUND(account_move_line.debit * currency_table.rate, currency_table.precision))   AS debit,
                    SUM(ROUND(account_move_line.credit * currency_table.rate, currency_table.precision))  AS credit,
                    SUM(ROUND(account_move_line.balance * currency_table.rate, currency_table.precision)) AS balance,
                    SUM(CASE WHEN account_move_line.currency_id = 1 THEN account_move_line.amount_currency ELSE 0 END) AS balance_usd
                FROM {tables}
                LEFT JOIN {ct_query} ON currency_table.company_id = account_move_line.company_id
                WHERE {where_clause}
                GROUP BY account_move_line.partner_id
            """)
    
        return ' UNION ALL '.join(queries), params


    def _query_partners(self, options):
        """ Executes the queries and performs all the computation.
        :return:        A list of tuple (partner, column_group_values) sorted by the table's model _order:
                        - partner is a res.parter record.
                        - column_group_values is a dict(column_group_key, fetched_values), where
                            - column_group_key is a string identifying a column group, like in options['column_groups']
                            - fetched_values is a dictionary containing:
                                - sum:                              {'debit': float, 'credit': float, 'balance': float}
                                - (optional) initial_balance:       {'debit': float, 'credit': float, 'balance': float}
                                - (optional) lines:                 [line_vals_1, line_vals_2, ...]
        """
        def assign_sum(row):
            fields_to_assign = ['balance', 'debit', 'credit','balance_usd']
            if any(not company_currency.is_zero(row[field]) for field in fields_to_assign):
                groupby_partners.setdefault(row['groupby'], defaultdict(lambda: defaultdict(float)))
                for field in fields_to_assign:
                    groupby_partners[row['groupby']][row['column_group_key']][field] += row[field]

        company_currency = self.env.company.currency_id

        # Execute the queries and dispatch the results.
        query, params = self._get_query_sums(options)
        groupby_partners = {}

        self._cr.execute(query, params)
        for res in self._cr.dictfetchall():
            assign_sum(res)
        # Correct the sums per partner, for the lines without partner reconciled with a line having a partner
        query, params = self._get_sums_without_partner(options)

        self._cr.execute(query, params)
        totals = {}
        for total_field in ['debit', 'credit', 'balance','balance_usd']:
            totals[total_field] = {col_group_key: 0 for col_group_key in options['column_groups']}

        for row in self._cr.dictfetchall():
            totals['debit'][row['column_group_key']] += row['debit']
            totals['credit'][row['column_group_key']] += row['credit']
            totals['balance'][row['column_group_key']] += row['balance']
            totals['balance_usd'][row['balance_usd']] += row['balance_usd']

            if row['groupby'] not in groupby_partners:
                continue

            assign_sum(row)
        if None in groupby_partners:
            # Debit/credit are inverted for the unknown partner as the computation is made regarding the balance of the known partner
            for column_group_key in options['column_groups']:
                groupby_partners[None][column_group_key]['debit'] += totals['credit'][column_group_key]
                groupby_partners[None][column_group_key]['credit'] += totals['debit'][column_group_key]
                groupby_partners[None][column_group_key]['balance'] -= totals['balance'][column_group_key]
                groupby_partners[None][column_group_key]['balance_usd'] -= totals['balance_usd'][column_group_key]
        # Retrieve the partners to browse.
        # groupby_partners.keys() contains all account ids affected by:
        # - the amls in the current period.
        # - the amls affecting the initial balance.
        if groupby_partners:
            # Note a search is done instead of a browse to preserve the table ordering.
            partners = self.env['res.partner'].with_context(active_test=False).search_fetch([('id', 'in', list(groupby_partners.keys()))], ["id", "name", "trust", "company_registry", "vat"])
        else:
            partners = []

        # Add 'Partner Unknown' if needed
        if None in groupby_partners.keys():
            partners = [p for p in partners] + [None]

        return [(partner, groupby_partners[partner.id if partner else None]) for partner in partners]


    def _build_partner_lines(self, report, options, level_shift=0):
            lines = []
    
            totals_by_column_group = {
                column_group_key: {
                    total: 0.0
                    for total in ['debit', 'credit', 'balance','balance_usd']
                }
                for column_group_key in options['column_groups']
            }
    
            partners_results = self._query_partners(options)
    
            search_filter = options.get('filter_search_bar', '')
            accept_unknown_in_filter = search_filter.lower() in self._get_no_partner_line_label().lower()
            for partner, results in partners_results:
                if options['export_mode'] == 'print' and search_filter and not partner and not accept_unknown_in_filter:
                    # When printing and searching for a specific partner, make it so we only show its lines, not the 'Unknown Partner' one, that would be
                    # shown in case a misc entry with no partner was reconciled with one of the target partner's entries.
                    continue
    
                partner_values = defaultdict(dict)
                for column_group_key in options['column_groups']:
                    partner_sum = results.get(column_group_key, {})
    
                    partner_values[column_group_key]['debit'] = partner_sum.get('debit', 0.0)
                    partner_values[column_group_key]['credit'] = partner_sum.get('credit', 0.0)
                    partner_values[column_group_key]['balance'] = partner_sum.get('balance', 0.0)
                    partner_values[column_group_key]['balance_usd'] = partner_sum.get('balance_usd', 0.0)
    
                    totals_by_column_group[column_group_key]['debit'] += partner_values[column_group_key]['debit']
                    totals_by_column_group[column_group_key]['credit'] += partner_values[column_group_key]['credit']
                    totals_by_column_group[column_group_key]['balance'] += partner_values[column_group_key]['balance']
                    totals_by_column_group[column_group_key]['balance_usd'] += partner_values[column_group_key]['balance_usd']
    
                lines.append(self._get_report_line_partners(options, partner, partner_values, level_shift=level_shift))
    
            return lines, totals_by_column_group

