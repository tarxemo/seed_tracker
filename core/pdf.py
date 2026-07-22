from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle

GREEN = colors.HexColor('#1a6b3c')
GREEN_LIGHT = colors.HexColor('#e8f5ee')
GREY = colors.HexColor('#7a8494')


def render_report_pdf(user, ctx):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ReportTitle', parent=styles['Title'], textColor=GREEN, fontSize=18, spaceAfter=2)
    subtitle_style = ParagraphStyle('ReportSubtitle', parent=styles['Normal'], textColor=GREY, fontSize=10, spaceAfter=14)
    section_style = ParagraphStyle('SectionHeading', parent=styles['Heading2'], textColor=GREEN, fontSize=13, spaceBefore=14, spaceAfter=6)

    elements = [
        Paragraph('Mbeya Seed Tracker &mdash; Report', title_style),
        Paragraph(
            f'{ctx["role_display"]} &bull; {ctx["org_context"]}<br/>Generated: {timezone.now().strftime("%d %b %Y %H:%M")}',
            subtitle_style,
        ),
    ]

    summary_rows = [
        ['Metric', 'Value'],
        [ctx['received_label'], f"{ctx['total_received']}"],
        [ctx['remaining_label'], f"{ctx['remaining_stock']}"],
        ['Total Distributed (kg)', f"{ctx['total_distributed']}"],
        ['Total Farmers', f"{ctx['total_farmers']}"],
        ['Total Allocations', f"{ctx['total_allocations']}"],
        ['Approved Allocations', f"{ctx['approved_allocations']}"],
        ['Distributed Allocations', f"{ctx['distributed_allocations']}"],
    ]
    elements.append(Paragraph('Summary', section_style))
    elements.append(_styled_table(summary_rows, [90 * mm, 60 * mm]))

    seed_rows = [['Seed Type', 'Allocations', 'Total Qty']]
    for s in ctx['seed_summary']:
        seed_rows.append([s['seed_type__name'], str(s['cnt']), f"{s['qty']} {s['seed_type__unit']}"])
    if len(seed_rows) > 1:
        elements.append(Paragraph('Seed Allocation Summary', section_style))
        elements.append(_styled_table(seed_rows, [70 * mm, 40 * mm, 40 * mm]))

    breakdown_rows = [[ctx['breakdown_label'], 'Allocations', 'Total Qty (kg)']]
    for b in ctx['breakdown']:
        breakdown_rows.append([b['label'], str(b['cnt']), str(b['qty'])])
    if len(breakdown_rows) > 1:
        elements.append(Paragraph(f'By {ctx["breakdown_label"]}', section_style))
        elements.append(_styled_table(breakdown_rows, [80 * mm, 35 * mm, 35 * mm]))

    doc.build(elements)
    buffer.seek(0)
    filename = f'seed_tracker_report_{user.username}_{timezone.now().strftime("%Y%m%d")}.pdf'
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _styled_table(rows, col_widths):
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), GREEN),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, GREEN_LIGHT]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#eef0f3')),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table
