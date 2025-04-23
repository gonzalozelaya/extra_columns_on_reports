# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
from datetime import datetime
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
        _logger.info(f" query list: {query_list}")
        self._cr.execute(full_query, full_query_params)
        results = self._cr.dictfetchall()
        _logger.info(f"Results: {results}")
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
            currency_name = result.get('currency_name', '')
            currency_rate = result.get('currency_rate', 0.0)
            tax_date = result.get('tax_date', result.get('date'))
            _logger.info(f'Tax date: {tax_date}')
            
            current_move_info['document_type'] = document_type
            current_move_info['currency_rate'] = currency_rate if currency_rate != 0 else 0
            current_move_info['currency_id'] = currency_name
            if tax_date:
                current_move_info['tax_date'] = tax_date.strftime("%d/%m/%Y")
            else:
                date_str = result.get('date', '')  # Obtener la fecha como string
                try:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()  # Convertirlo a date
                    current_move_info['tax_date'] = date_obj.strftime("%d/%m/%Y")  # Formatearlo
                except ValueError:
                    current_move_info['tax_date'] = ''
            
            totals = total_values_dict[column_group_key]
            for key in number_keys:
                result[key] = sign * result[key]
                totals[key] += result[key]

        lines = [
            (0, self._create_report_line(report, options, move_info, move_id, number_keys))
            for move_id, move_info in move_info_dict.items()
        ]
        if lines:  # Solo si hay líneas para mostrar
            total_line = self._create_total_line(report, options, total_values_dict, number_keys)
            lines.append((0, total_line))
        
        return lines

    def _create_total_line(self, report, options, total_values_dict, number_keys):
        columns = []
        for column in options['columns']:
            expression_label = column['expression_label']
            
            if expression_label in ['document_type', 'currency_rate', 'currency_id', 'tax_date','afip_responsibility_type_name']:
                value = ''
            else:
                # Obtener el valor total para esta columna
                column_group_key = column['column_group_key']
                value = total_values_dict.get(column_group_key, {}).get(expression_label, '')
            
            columns.append(report._build_column_dict(value, column, options=options))
    
        return {
            'id': report._get_generic_line_id('account.tax.report.total', 0),
            'name': _("Total"),
            'columns': columns,
            'level': 1,
            'class': 'total',
        }
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
            elif expression_label == 'tax_date':
                value = move_vals.get('tax_date', '')
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


    def _vat_book_get_txt_invoices(self, options):
        state = options.get('all_entries') and 'all' or 'posted'
        if state != 'posted':
            raise UserError(_('Can only generate TXT files using posted entries.'
                              ' Please remove Include unposted entries filter and try again'))

        domain = [('l10n_latam_document_type_id.code', '!=', False)] + self._vat_book_get_lines_domain(options)
        txt_type = options.get('txt_type')
        if txt_type == 'purchases':
            domain += [('l10n_latam_document_type_id.code', 'not in', ['66', '30', '32'])]
        elif txt_type == 'goods_import':
            domain += [('l10n_latam_document_type_id.code', '=', '66')]
        elif txt_type == 'used_goods':
            domain += [('l10n_latam_document_type_id.code', 'in', ['30', '32'])]
        return self.env['account.move'].search(
                domain, 
                order='invoice_date asc, name asc, id asc'
            )

    def _vat_book_get_lines_domain(self, options):
        company_ids = self.env.company.ids
        selected_journal_types = self._vat_book_get_selected_tax_types(options)
        domain = [
            ('journal_id.type', 'in', selected_journal_types),
            ('journal_id.l10n_latam_use_documents', '=', True),
            ('company_id', 'in', company_ids),
        ]
        state = options.get('all_entries') and 'all' or 'posted'
        if state and state.lower() != 'all':
            domain += [('state', '=', state)]
    
        # Obtener las fechas desde `options`
        date_from = options.get('date', {}).get('date_from')
        date_to = options.get('date', {}).get('date_to')
    
        # Aplicar filtro por tax_date, con fallback a date si no está disponible
        # Aplicar correctamente la condición de fecha
        if date_from and date_to:
            domain.append('&')  # Necesitamos que ambas condiciones sean verdaderas
            domain.append('|')  # Aplicamos el OR para tax_date o date
            domain.append(('tax_date', '>=', date_from))
            domain.append(('date', '>=', date_from))
    
            domain.append('|')
            domain.append(('tax_date', '<=', date_to))
            domain.append(('date', '<=', date_to))
    
        elif date_from:
            domain.append('|')
            domain.append(('tax_date', '>=', date_from))
            domain.append(('date', '>=', date_from))
    
        elif date_to:
            domain.append('|')
            domain.append(('tax_date', '<=', date_to))
            domain.append(('date', '<=', date_to))
        
        return domain

    
    def _vat_book_get_txt_files(self, options, tax_type):
        """ Compute the date to be printed in the txt files"""
        lines = []
        invoices = self._vat_book_get_txt_invoices(options)
        aliquots = self._vat_book_get_REGINFO_CV_ALICUOTAS(options, tax_type, invoices)
        _logger.info("Facturas: %s", [(inv.id, inv.name, inv.partner_id.name, inv.amount_total,inv.tax_date) for inv in invoices])
        for v in aliquots.values():
            lines += v
        aliquots_data = '\r\n'.join(lines).encode('ISO-8859-1')
        vouchers_data = '\r\n'.join(self._vat_book_get_REGINFO_CV_CBTE(options, aliquots, tax_type, invoices)).encode('ISO-8859-1', 'ignore')
        return vouchers_data, aliquots_data
    
    def _vat_book_get_REGINFO_CV_CBTE(self, options, aliquots, tax_type, invoices):
        res = []

        for inv in invoices:
            aliquots_count = len(aliquots.get(inv))

            currency_rate = inv.l10n_ar_currency_rate
            currency_code = inv.currency_id.l10n_ar_afip_code

            invoice_number, pos_number = self._vat_book_get_pos_and_invoice_invoice_number(inv)
            doc_code, doc_number = self._vat_book_get_partner_document_code_and_number(inv.partner_id)

            amounts = inv._l10n_ar_get_amounts()
            vat_amount = amounts['vat_amount']
            vat_exempt_base_amount = amounts['vat_exempt_base_amount']
            vat_untaxed_base_amount = amounts['vat_untaxed_base_amount']
            other_taxes_amount = amounts['other_taxes_amount']
            vat_perc_amount = amounts['vat_perc_amount']
            iibb_perc_amount = amounts['iibb_perc_amount']
            mun_perc_amount = amounts['mun_perc_amount']
            intern_tax_amount = amounts['intern_tax_amount']
            perc_imp_nacionales_amount = amounts['profits_perc_amount'] + amounts['other_perc_amount']
            if inv.move_type in ('out_refund', 'in_refund') and \
                    inv.l10n_latam_document_type_id.code in inv._get_l10n_ar_codes_used_for_inv_and_ref():
                amount_total = -inv.amount_total
            else:
                amount_total = inv.amount_total

            if vat_exempt_base_amount:
                if inv.partner_id.l10n_ar_afip_responsibility_type_id.code == '10':  # free zone operation
                    operation_code = 'Z'
                elif inv.l10n_latam_document_type_id.l10n_ar_letter == 'E':          # exportation operation
                    operation_code = 'X'
                else:                                                                # exempt operation
                    operation_code = 'E'
            elif inv.l10n_latam_document_type_id.code == '66':                       # import clearance
                operation_code = 'E'
            elif vat_untaxed_base_amount:                                            # not taxed operation
                operation_code = 'N'
            else:
                operation_code = ' '
            row = [
                inv.invoice_date.strftime('%Y%m%d'),  # Field 1: Fecha de comprobante
                f"{int(inv.l10n_latam_document_type_id.code):0>3d}",  # Field 2: Tipo de Comprobante.
                pos_number,  # Field 3: Punto de Venta
                invoice_number,  # Field 4: Número de Comprobante
                # If it is a multiple-sheet receipt, the document number of the first sheet must be reported, taking into account the provisions of article 23, paragraph a), point 6. of General Resolution No. 1,415, the related resolutions that modify and complement this one.
                # In the case of registering grouped by daily totals, the first voucher number of the range to be considered must be entered.
            ]

            if tax_type == 'sale':
                # Field 5: Número de Comprobante Hasta: En el resto de los casos se consignará el dato registrado en el campo 4
                row.append(invoice_number)
            else:
                # Field 5: Despacho de importación
                if inv.l10n_latam_document_type_id.code == '66':
                    row.append((inv.l10n_latam_document_number).rjust(16, '0'))
                else:
                    row.append(''.rjust(16, ' '))
            row += [
                doc_code,  # Field 6: Código de documento del comprador.
                doc_number,  # Field 7: Número de Identificación del comprador
                inv.commercial_partner_id.name.ljust(30, ' ')[:30],  # Field 8: Apellido y Nombre del comprador.
                self._vat_book_format_amount(amount_total),  # Field 9: Importe Total de la Operación.
                self._vat_book_format_amount(vat_untaxed_base_amount),  # Field 10: Importe total de conceptos que no integran el precio neto gravado
            ]

            if tax_type == 'sale':
                row += [
                    self._vat_book_format_amount(0.0),  # Field 11: Percepción a no categorizados
                    # the "uncategorized / responsible not registered" figure is not used anymore
                    self._vat_book_format_amount(vat_exempt_base_amount),  # Field 12: Importe de operaciones exentas
                    self._vat_book_format_amount(perc_imp_nacionales_amount + vat_perc_amount),  # Field 13: Importe de percepciones o pagos a cuenta de impuestos Nacionales
                ]
            else:
                row += [
                    self._vat_book_format_amount(vat_exempt_base_amount),  # Field 11: Importe de operaciones exentas
                    self._vat_book_format_amount(vat_perc_amount),  # Field 12: Importe de percepciones o pagos a cuenta del Impuesto al Valor Agregado
                    self._vat_book_format_amount(perc_imp_nacionales_amount),  # Field 13: Importe de percepciones o pagos a cuenta otros impuestos nacionales
                ]

            row += [
                self._vat_book_format_amount(iibb_perc_amount),  # Field 14: Importe de percepciones de ingresos brutos
                self._vat_book_format_amount(mun_perc_amount),  # Field 15: Importe de percepciones de impuestos municipales
                self._vat_book_format_amount(intern_tax_amount),  # Field 16: Importe de impuestos internos
                str(currency_code),  # Field 17: Código de Moneda

                self._vat_book_format_amount(currency_rate, padding=10, decimals=6),  # Field 18: Tipo de Cambio
                # new modality of currency_rate

                str(aliquots_count),  # Field 19: Cantidad de alícuotas de IVA
                operation_code,  # Field 20: Código de operación.
            ]

            if tax_type == 'sale':
                document_codes = [
                    '16', '19', '20', '21', '22', '23', '24', '27', '28', '29', '33', '34', '35', '37', '38', '43', '44',
                    '45', '46', '47', '48', '49', '54', '55', '56', '57', '58', '59', '60', '61', '68', '81', '82', '83',
                    '110', '111', '112', '113', '114', '115', '116', '117', '118', '119', '120', '150', '151', '157',
                    '158', '159', '160', '161', '162', '163', '164', '165', '166', '167', '168', '169', '170', '171',
                    '172', '180', '182', '183', '185', '186', '188', '189', '190', '191',
                    '201', '202', '203', '206', '207', '208', '211', '212', '213', '331', '332']
                row += [
                    # Field 21: Otros Tributos
                    self._vat_book_format_amount(other_taxes_amount),

                    # Field 22: vencimiento comprobante
                    # NOTE: it does not appear in instructions but it does in application. for ticket and export invoice is not reported, also for some others but that we do not have implemented
                    inv.l10n_latam_document_type_id.code in document_codes and '00000000' or inv.invoice_date_due.strftime('%Y%m%d')
                ]
            else:
                row.append(self._vat_book_format_amount(0.0 if inv.company_id.l10n_ar_computable_tax_credit == 'global' else vat_amount))  # Field 21: Crédito Fiscal Computable

                liquido_type = inv.l10n_latam_document_type_id.code in ['33', '58', '59', '60', '63']
                row += [
                    self._vat_book_format_amount(other_taxes_amount),  # Field 22: Otros Tributos

                    # NOTE: still not implemented on this three fields for use case with third pary commisioner

                    # Field 23: CUIT Emisor / Corredor
                    # It will be reported only if the field 'Tipo de Comprobante' contains '33', '58', '59', '60' or '63'. if there is no intervention of third party in the operation then the informant VAT number will be reported. For the rest of the vouchers it will be completed with zeros
                    liquido_type and inv.company_id.partner_id.ensure_vat() or '0' * 11,

                    (liquido_type and inv.company_id.name or '').ljust(30, ' ')[:30],  # Field 24: Denominación Emisor / Corredor

                    # Field 25: IVA Comisión
                    # If field 23 is different from zero, then we will add the VAT tax base amount of thecommission
                    self._vat_book_format_amount(0),
                ]
            res.append(''.join(row))
        return res

   
