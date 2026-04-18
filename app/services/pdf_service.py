"""
PDF report generation service for consultations.
Uses xhtml2pdf to generate professional PDF reports from HTML templates.
"""
import io
import os
from datetime import datetime
from typing import List, Optional
from pathlib import Path


def _format_date(dt) -> str:
    """Format a datetime to French date string."""
    if not dt:
        return ""
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        months = [
            "", "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre"
        ]
        return f"{dt.day} {months[dt.month]} {dt.year}"
    except Exception:
        return str(dt)


def _format_time(dt) -> str:
    """Format a datetime to HH:MM."""
    if not dt:
        return ""
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return str(dt)


def _safe(val, default=""):
    """Safely get a value, return default if None."""
    return val if val is not None else default


def generate_consultation_pdf(appointment, doctor, patient, consultations) -> bytes:
    """Generate a professional PDF report for a consultation."""

    doctor_name = f"Dr. {_safe(getattr(doctor, 'first_name', ''))} {_safe(getattr(doctor, 'last_name', ''))}"
    patient_name = f"{_safe(getattr(patient, 'first_name', ''))} {_safe(getattr(patient, 'last_name', ''))}"
    date_str = _format_date(getattr(appointment, 'appointment_date', None))
    time_str = _format_time(getattr(appointment, 'appointment_date', None))

    # Safe consultation type access
    ct = getattr(appointment, 'consultation_type', None)
    ct_val = getattr(ct, 'value', str(ct)) if ct else ''
    consult_type = "Teleconsultation" if ct_val == "online" else "En cabinet"

    fee_val = getattr(appointment, 'consultation_fee', None)
    currency_val = getattr(appointment, 'currency', 'TND')
    fee = f"{fee_val} {currency_val}" if fee_val else "-"

    specialty = _safe(getattr(doctor, 'specialty', ''))
    cabinet_city = _safe(getattr(doctor, 'cabinet_city', ''))
    confirmation_code = _safe(getattr(appointment, 'confirmation_code', ''))

    # Build consultation notes HTML
    notes_html = ""
    if consultations:
        for i, c in enumerate(consultations):
            vitals = getattr(c, 'vitals', None) or {}
            prescriptions = getattr(c, 'prescriptions', None) or []

            vitals_html = ""
            if any([vitals.get("blood_pressure"), vitals.get("heart_rate"), vitals.get("temperature"), vitals.get("weight")]):
                vitals_items = ""
                if vitals.get("blood_pressure"):
                    vitals_items += f'<td style="text-align:center;padding:8px;background:#FFF;border:1px solid #E5E7EB;"><div style="font-size:9px;color:#9CA3AF;">Tension</div><div style="font-size:13px;font-weight:bold;">{vitals["blood_pressure"]}</div></td>'
                if vitals.get("heart_rate"):
                    vitals_items += f'<td style="text-align:center;padding:8px;background:#FFF;border:1px solid #E5E7EB;"><div style="font-size:9px;color:#9CA3AF;">Pouls</div><div style="font-size:13px;font-weight:bold;">{vitals["heart_rate"]} bpm</div></td>'
                if vitals.get("temperature"):
                    vitals_items += f'<td style="text-align:center;padding:8px;background:#FFF;border:1px solid #E5E7EB;"><div style="font-size:9px;color:#9CA3AF;">Temperature</div><div style="font-size:13px;font-weight:bold;">{vitals["temperature"]}C</div></td>'
                if vitals.get("weight"):
                    vitals_items += f'<td style="text-align:center;padding:8px;background:#FFF;border:1px solid #E5E7EB;"><div style="font-size:9px;color:#9CA3AF;">Poids</div><div style="font-size:13px;font-weight:bold;">{vitals["weight"]} kg</div></td>'
                vitals_html = f'<div style="margin-bottom:12px;"><div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;font-weight:bold;margin-bottom:4px;">Signes vitaux</div><table style="width:100%;"><tr>{vitals_items}</tr></table></div>'

            rx_html = ""
            if prescriptions:
                rx_rows = ""
                for p in prescriptions:
                    med = p.get("medication", "") if isinstance(p, dict) else getattr(p, "medication", "")
                    dos = p.get("dosage", "") if isinstance(p, dict) else getattr(p, "dosage", "")
                    freq = p.get("frequency", "") if isinstance(p, dict) else getattr(p, "frequency", "")
                    dur = p.get("duration", "") if isinstance(p, dict) else getattr(p, "duration", "")
                    rx_rows += f"<tr><td style='padding:6px 10px;font-size:10px;border-bottom:1px solid #F3F4F6;color:#4B5563;'>{med}</td><td style='padding:6px 10px;font-size:10px;border-bottom:1px solid #F3F4F6;color:#4B5563;'>{dos}</td><td style='padding:6px 10px;font-size:10px;border-bottom:1px solid #F3F4F6;color:#4B5563;'>{freq}</td><td style='padding:6px 10px;font-size:10px;border-bottom:1px solid #F3F4F6;color:#4B5563;'>{dur}</td></tr>"
                rx_html = f"""<div style="margin-bottom:12px;">
                    <div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;font-weight:bold;margin-bottom:4px;">Prescriptions</div>
                    <table style="width:100%;border-collapse:collapse;margin-top:5px;">
                        <tr><th style="background:#E5E7EB;padding:6px 10px;font-size:9px;text-transform:uppercase;text-align:left;color:#374151;">Medicament</th><th style="background:#E5E7EB;padding:6px 10px;font-size:9px;text-transform:uppercase;text-align:left;color:#374151;">Dosage</th><th style="background:#E5E7EB;padding:6px 10px;font-size:9px;text-transform:uppercase;text-align:left;color:#374151;">Frequence</th><th style="background:#E5E7EB;padding:6px 10px;font-size:9px;text-transform:uppercase;text-align:left;color:#374151;">Duree</th></tr>
                        {rx_rows}
                    </table>
                </div>"""

            follow_up_html = ""
            fu_date = getattr(c, 'follow_up_date', None)
            fu_notes = getattr(c, 'follow_up_notes', None)
            if fu_date:
                follow_up_html = f"""<div style="background:#EFF6FF;border:1px solid #BFDBFE;padding:10px 12px;margin-top:10px;font-size:11px;color:#1E40AF;">
                    <strong>Suivi prevu :</strong> {_format_date(fu_date)}
                    {f' - {fu_notes}' if fu_notes else ''}
                </div>"""

            created = _format_date(getattr(c, 'created_at', None))
            chief_complaint = _safe(getattr(c, 'chief_complaint', ''))
            diagnosis = _safe(getattr(c, 'diagnosis', ''))
            notes_text = _safe(getattr(c, 'notes', ''))
            treatment_plan = _safe(getattr(c, 'treatment_plan', ''))

            cc_html = f'<div style="margin-bottom:12px;"><div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;font-weight:bold;margin-bottom:4px;">Motif de consultation</div><p style="margin:0;font-size:11px;color:#374151;">{chief_complaint}</p></div>' if chief_complaint else ''
            diag_html = f'<div style="margin-bottom:12px;"><div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;font-weight:bold;margin-bottom:4px;">Diagnostic</div><p style="margin:0;font-size:11px;color:#374151;">{diagnosis}</p></div>' if diagnosis else ''
            notes_sec = f'<div style="margin-bottom:12px;"><div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;font-weight:bold;margin-bottom:4px;">Notes</div><p style="margin:0;font-size:11px;color:#374151;">{notes_text}</p></div>' if notes_text else ''
            tp_html = f'<div style="margin-bottom:12px;"><div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;font-weight:bold;margin-bottom:4px;">Plan de traitement</div><p style="margin:0;font-size:11px;color:#374151;">{treatment_plan}</p></div>' if treatment_plan else ''

            notes_html += f"""
            <div style="background:#F9FAFB;border:1px solid #E5E7EB;padding:15px;margin-bottom:15px;">
                <div style="border-bottom:1px solid #E5E7EB;padding-bottom:8px;margin-bottom:12px;">
                    <span style="font-size:10px;font-weight:bold;color:#2563EB;text-transform:uppercase;letter-spacing:1px;">Note #{i + 1}</span>
                    <span style="float:right;font-size:10px;color:#9CA3AF;">{created}</span>
                </div>
                {cc_html}
                {diag_html}
                {notes_sec}
                {tp_html}
                {vitals_html}
                {rx_html}
                {follow_up_html}
            </div>"""
    else:
        notes_html = '<div style="text-align:center;padding:30px;color:#9CA3AF;background:#F9FAFB;border:1px dashed #D1D5DB;">Aucune note de consultation disponible</div>'

    generated_date = _format_date(datetime.now())

    # Get absolute path to the logo in the static directory
    base_dir = Path(__file__).parent.parent
    logo_path = os.path.join(base_dir, 'static', 'logo.png')
    # Using file:/// protocol for local files with xhtml2pdf usually works best,
    # or just the absolute OS path.
    # Convert path to posix format for HTML src
    logo_src = logo_path.replace('\\', '/')
    
    # Use a premium design with elegant typography and clean boxes
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8"/>
    <style>
        @page {{
            size: A4;
            margin: 2cm 1.5cm 2cm 1.5cm;
            @frame footer {{
                -pdf-frame-content: footerContent;
                bottom: 1cm;
                margin-left: 1.5cm;
                margin-right: 1.5cm;
                height: 1cm;
            }}
        }}
        body {{
            font-family: Helvetica, Arial, sans-serif;
            color: #1F2937;
            font-size: 11px;
            line-height: 1.4;
        }}
        .text-primary {{ color: #2563EB; }}
        .text-secondary {{ color: #6B7280; }}
        .text-dark {{ color: #111827; }}
        .bg-light {{ background-color: #F8FAFC; }}
    </style>
</head>
<body>
    <!-- Header -->
    <table style="width: 100%; border-bottom: 2px solid #2563EB; padding-bottom: 15px; margin-bottom: 25px;">
        <tr>
            <td style="width: 20%; vertical-align: middle;">
                <img src="{logo_src}" style="width: 70px; height: 70px;" />
            </td>
            <td style="width: 50%; vertical-align: middle;">
                <h1 style="font-size: 24px; font-weight: bold; color: #2563EB; margin: 0; letter-spacing: -0.5px;">Rapport de Consultation</h1>
                <div style="font-size: 10px; color: #6B7280; margin-top: 4px; text-transform: uppercase; letter-spacing: 1px;">Document Médical Confidentiel</div>
            </td>
            <td style="width: 30%; text-align: right; vertical-align: middle;">
                <div style="font-size: 10px; color: #9CA3AF;">Généré le</div>
                <div style="font-size: 12px; font-weight: bold; color: #374151;">{generated_date}</div>
            </td>
        </tr>
    </table>

    <!-- Info Section -->
    <table style="width: 100%; margin-bottom: 25px;">
        <tr>
            <!-- Doctor Info -->
            <td style="width: 48%; vertical-align: top;">
                <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 15px; border-radius: 4px;">
                    <div style="font-size: 9px; text-transform: uppercase; letter-spacing: 1.5px; color: #64748B; font-weight: bold; margin-bottom: 8px;">Médecin Traitant</div>
                    <div style="font-size: 16px; font-weight: bold; color: #0F172A; margin-bottom: 4px;">{doctor_name}</div>
                    {'<div style="font-size: 11px; color: #475569; margin-bottom: 2px;">Spécialité: ' + specialty + '</div>' if specialty else ''}
                    {'<div style="font-size: 11px; color: #475569;">Cabinet: ' + cabinet_city + '</div>' if cabinet_city else ''}
                </div>
            </td>
            <td style="width: 4%;">&nbsp;</td>
            <!-- Patient Info -->
            <td style="width: 48%; vertical-align: top;">
                <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 15px; border-radius: 4px;">
                    <div style="font-size: 9px; text-transform: uppercase; letter-spacing: 1.5px; color: #64748B; font-weight: bold; margin-bottom: 8px;">Patient</div>
                    <div style="font-size: 16px; font-weight: bold; color: #0F172A; margin-bottom: 4px;">{patient_name}</div>
                    {'<div style="font-size: 11px; color: #475569;">Code de consultation: <strong>' + confirmation_code + '</strong></div>' if confirmation_code else ''}
                </div>
            </td>
        </tr>
    </table>

    <!-- Appointment Meta -->
    <div style="background-color: #EFF6FF; border: 1px solid #BFDBFE; border-left: 4px solid #3B82F6; padding: 12px 15px; margin-bottom: 30px;">
        <table style="width: 100%; font-size: 11px; color: #1E3A8A;">
            <tr>
                <td style="width: 25%;"><strong>Date:</strong> {date_str}</td>
                <td style="width: 25%;"><strong>Heure:</strong> {time_str}</td>
                <td style="width: 25%;"><strong>Type:</strong> {consult_type}</td>
                <td style="width: 25%;"><strong>Honoraires:</strong> {fee}</td>
            </tr>
        </table>
    </div>

    <!-- Notes Section -->
    <div style="font-size: 16px; font-weight: bold; color: #0F172A; border-bottom: 2px solid #E2E8F0; padding-bottom: 8px; margin-bottom: 20px;">
        Détails de la Consultation
    </div>
    
    {notes_html}

    <!-- Footer Content for xhtml2pdf -->
    <div id="footerContent" style="text-align: center; border-top: 1px solid #E2E8F0; padding-top: 10px; font-size: 9px; color: #94A3B8;">
        Ce rapport a été généré sécuritairement par l'application <strong>MediConnect</strong>.<br/>
        Page <pdf:pagenumber> sur <pdf:pagecount>
    </div>
</body>
</html>"""

    # Convert HTML to PDF
    from xhtml2pdf import pisa
    result = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html), dest=result)
    if pisa_status.err:
        raise Exception(f"PDF generation failed: {pisa_status.err}")
    return result.getvalue()
