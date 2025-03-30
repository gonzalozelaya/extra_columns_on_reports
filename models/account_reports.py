from odoo import models
import markupsafe

class AccountReportFootnote(models.Model):
    _inherit = 'account.report'
    
    def _get_pdf_export_html(self, options, lines, additional_context=None, template=None):
        report_info = self.get_report_information(options)
    
        custom_print_templates = report_info['custom_display'].get('pdf_export', {})
        template = custom_print_templates.get('pdf_export_main', 'account_reports.pdf_export_main')
        
        # Determinar el título del reporte
        if 'ar_vat_book_tax_type_selected' in options:
            title = ''
            if options['ar_vat_book_tax_type_selected'] == 'purchase':
                title = 'COMPRAS'
            elif options['ar_vat_book_tax_type_selected'] == 'sale':
                title = 'VENTAS'
            report_title = f"LIBRO IVA {title}"
        else:
            report_title = self.name
        
        render_values = {
            'report': self,
            'report_title': report_title,  # Usamos el título condicional aquí
            'options': options,
            'table_start': markupsafe.Markup('<tbody>'),
            'table_end': markupsafe.Markup('''
                </tbody></table>
                <div style="page-break-after: always"></div>
                <table class="o_table table-hover">
            '''),
            'column_headers_render_data': self._get_column_headers_render_data(options),
            'custom_templates': custom_print_templates,
        }
        if additional_context:
            render_values.update(additional_context)

        if options.get('order_column'):
            lines = self.sort_lines(lines, options)

        lines = self._format_lines_for_display(lines, options)

        render_values['lines'] = lines

        # Manage footnotes.
        footnotes_to_render = []
        number = 0
        for line in lines:
            footnote_data = report_info['footnotes'].get(str(line.get('id')))
            if footnote_data:
                number += 1
                line['footnote'] = str(number)
                footnotes_to_render.append({'id': footnote_data['id'], 'number': number, 'text': footnote_data['text']})

        render_values['footnotes'] = footnotes_to_render

        options['css_custom_class'] = report_info['custom_display'].get('css_custom_class', '')

        # Render.
        return self.env['ir.qweb']._render(template, render_values)