"""
Doctor Cabinet Statistics API
Provides comprehensive analytics for doctor dashboards.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, extract, and_, distinct, cast, Date
from datetime import datetime, timedelta
from typing import Optional
import io

from app.core.database import get_db
from app.models.user import User
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.appointment import Appointment, AppointmentStatus, ConsultationType
from app.api.deps import get_current_active_user

router = APIRouter(prefix="/statistics", tags=["Statistics"])


async def get_doctor_from_user(db: AsyncSession, user: User) -> Doctor:
    """Get doctor profile from user."""
    result = await db.execute(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can access statistics"
        )
    return doctor


@router.get("/dashboard")
async def get_dashboard_statistics(
    period: str = "all",  # "week", "month", "3months", "6months", "year", "all"
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive cabinet statistics for a doctor.
    
    Returns all metrics needed for the dashboard in a single response.
    """
    doctor = await get_doctor_from_user(db, current_user)
    doctor_id = doctor.id
    
    # Determine date filter based on period
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    period_start = None
    if period == "week":
        period_start = now - timedelta(weeks=1)
    elif period == "month":
        period_start = now - timedelta(days=30)
    elif period == "3months":
        period_start = now - timedelta(days=90)
    elif period == "6months":
        period_start = now - timedelta(days=180)
    elif period == "year":
        period_start = now - timedelta(days=365)
    # "all" → period_start remains None (no date filter)
    
    # Base query filter
    base_filter = [Appointment.doctor_id == doctor_id]
    if period_start:
        base_filter.append(Appointment.appointment_date >= period_start)
    
    # ============================================================
    # 1. OVERVIEW COUNTS
    # ============================================================
    overview_result = await db.execute(
        select(
            func.count(Appointment.id).label("total"),
            func.count(distinct(Appointment.patient_id)).label("unique_patients"),
            func.count(case(
                (Appointment.status == AppointmentStatus.COMPLETED, 1)
            )).label("completed"),
            func.count(case(
                (Appointment.status == AppointmentStatus.CONFIRMED, 1)
            )).label("confirmed"),
            func.count(case(
                (Appointment.status == AppointmentStatus.PENDING, 1)
            )).label("pending"),
            func.count(case(
                (Appointment.status == AppointmentStatus.CANCELLED, 1)
            )).label("cancelled"),
            func.count(case(
                (Appointment.status == AppointmentStatus.NO_SHOW, 1)
            )).label("no_show"),
            func.count(case(
                (Appointment.status == AppointmentStatus.RESCHEDULED, 1)
            )).label("rescheduled"),
        ).where(and_(*base_filter))
    )
    overview = overview_result.one()
    
    total = overview.total or 0
    completed = overview.completed or 0
    cancelled = overview.cancelled or 0
    no_show = overview.no_show or 0
    confirmed = overview.confirmed or 0
    pending = overview.pending or 0
    rescheduled = overview.rescheduled or 0
    unique_patients = overview.unique_patients or 0
    
    completion_rate = round((completed / total * 100), 1) if total > 0 else 0
    cancellation_rate = round((cancelled / total * 100), 1) if total > 0 else 0
    no_show_rate = round((no_show / total * 100), 1) if total > 0 else 0
    
    # ============================================================
    # 2. CONSULTATION TYPE DISTRIBUTION (Présentiel vs Online)
    # ============================================================
    type_result = await db.execute(
        select(
            Appointment.consultation_type,
            func.count(Appointment.id).label("count")
        ).where(and_(*base_filter))
        .group_by(Appointment.consultation_type)
    )
    type_rows = type_result.all()
    
    presentiel_count = 0
    online_count = 0
    for row in type_rows:
        if row.consultation_type == ConsultationType.PRESENTIEL:
            presentiel_count = row.count
        elif row.consultation_type == ConsultationType.ONLINE:
            online_count = row.count
    
    # ============================================================
    # 3. REVENUE STATISTICS
    # ============================================================
    revenue_result = await db.execute(
        select(
            func.coalesce(func.sum(
                case((Appointment.is_paid == True, Appointment.consultation_fee), else_=0)
            ), 0).label("total_revenue"),
            func.coalesce(func.sum(
                case((Appointment.is_paid == False, Appointment.consultation_fee), else_=0)
            ), 0).label("pending_revenue"),
            func.coalesce(func.sum(Appointment.consultation_fee), 0).label("potential_revenue"),
            func.coalesce(func.avg(
                case((Appointment.is_paid == True, Appointment.consultation_fee))
            ), 0).label("avg_fee"),
        ).where(
            and_(
                *base_filter,
                Appointment.status.in_([
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.PENDING,
                ])
            )
        )
    )
    rev = revenue_result.one()
    
    # ============================================================
    # 4. MONTHLY TRENDS (last 6 months always, for charts)
    # ============================================================
    six_months_ago = now - timedelta(days=180)
    
    monthly_result = await db.execute(
        select(
            extract('year', Appointment.appointment_date).label("year"),
            extract('month', Appointment.appointment_date).label("month"),
            func.count(Appointment.id).label("total"),
            func.count(case(
                (Appointment.status == AppointmentStatus.COMPLETED, 1)
            )).label("completed"),
            func.count(case(
                (Appointment.status == AppointmentStatus.CANCELLED, 1)
            )).label("cancelled"),
            func.coalesce(func.sum(
                case((Appointment.is_paid == True, Appointment.consultation_fee), else_=0)
            ), 0).label("revenue"),
        ).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date >= six_months_ago,
            )
        )
        .group_by(
            extract('year', Appointment.appointment_date),
            extract('month', Appointment.appointment_date)
        )
        .order_by(
            extract('year', Appointment.appointment_date),
            extract('month', Appointment.appointment_date)
        )
    )
    monthly_rows = monthly_result.all()
    
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    monthly_data = []
    for row in monthly_rows:
        m_idx = int(row.month) - 1
        monthly_data.append({
            "month": month_names[m_idx],
            "year": int(row.year),
            "total": row.total,
            "completed": row.completed,
            "cancelled": row.cancelled,
            "revenue": float(row.revenue),
        })
    
    # ============================================================
    # 5. TODAY'S SUMMARY
    # ============================================================
    today_result = await db.execute(
        select(
            func.count(Appointment.id).label("total"),
            func.count(case(
                (Appointment.status == AppointmentStatus.COMPLETED, 1)
            )).label("completed"),
            func.count(case(
                (Appointment.status == AppointmentStatus.CONFIRMED, 1)
            )).label("confirmed"),
            func.count(case(
                (Appointment.status == AppointmentStatus.PENDING, 1)
            )).label("pending"),
            func.count(case(
                (Appointment.status == AppointmentStatus.CANCELLED, 1)
            )).label("cancelled"),
            func.count(case(
                (Appointment.consultation_type == ConsultationType.ONLINE, 1)
            )).label("online"),
            func.count(case(
                (Appointment.consultation_type == ConsultationType.PRESENTIEL, 1)
            )).label("presentiel"),
        ).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date >= today_start,
                Appointment.appointment_date < today_end,
            )
        )
    )
    today = today_result.one()
    
    # ============================================================
    # 6. WEEKLY TREND (last 7 days, one data point per day)
    # ============================================================
    seven_days_ago = today_start - timedelta(days=6)
    
    daily_result = await db.execute(
        select(
            cast(Appointment.appointment_date, Date).label("day"),
            func.count(Appointment.id).label("total"),
        ).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date >= seven_days_ago,
                Appointment.appointment_date < today_end,
            )
        )
        .group_by(cast(Appointment.appointment_date, Date))
        .order_by(cast(Appointment.appointment_date, Date))
    )
    daily_rows = daily_result.all()
    
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    daily_data = []
    for i in range(7):
        d = seven_days_ago + timedelta(days=i)
        count = 0
        for row in daily_rows:
            if row.day == d.date():
                count = row.total
        daily_data.append({
            "day": day_names[d.weekday()],
            "date": d.strftime("%Y-%m-%d"),
            "count": count,
        })
    
    # ============================================================
    # 7. PEAK HOURS (which hours are busiest)
    # ============================================================
    hours_result = await db.execute(
        select(
            extract('hour', Appointment.appointment_date).label("hour"),
            func.count(Appointment.id).label("count"),
        ).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.status.in_([
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.CONFIRMED,
                ])
            )
        )
        .group_by(extract('hour', Appointment.appointment_date))
        .order_by(extract('hour', Appointment.appointment_date))
    )
    hours_rows = hours_result.all()
    
    peak_hours = [
        {"hour": int(row.hour), "count": row.count}
        for row in hours_rows
    ]
    
    # ============================================================
    # 8. TOP PATIENTS (most frequent)
    # ============================================================
    top_patients_result = await db.execute(
        select(
            Appointment.patient_id,
            func.count(Appointment.id).label("visit_count"),
        ).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.status.in_([
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.CONFIRMED,
                ])
            )
        )
        .group_by(Appointment.patient_id)
        .order_by(func.count(Appointment.id).desc())
        .limit(5)
    )
    top_patient_rows = top_patients_result.all()
    
    top_patients = []
    for row in top_patient_rows:
        patient_result = await db.execute(
            select(Patient).where(Patient.id == row.patient_id)
        )
        patient = patient_result.scalar_one_or_none()
        if patient:
            top_patients.append({
                "id": str(row.patient_id),
                "name": f"{patient.first_name} {patient.last_name}",
                "visit_count": row.visit_count,
            })
    
    # ============================================================
    # ASSEMBLE RESPONSE
    # ============================================================
    return {
        "period": period,
        "generated_at": now.isoformat(),
        
        "overview": {
            "total_appointments": total,
            "unique_patients": unique_patients,
            "completed": completed,
            "confirmed": confirmed,
            "pending": pending,
            "cancelled": cancelled,
            "no_show": no_show,
            "rescheduled": rescheduled,
            "completion_rate": completion_rate,
            "cancellation_rate": cancellation_rate,
            "no_show_rate": no_show_rate,
        },
        
        "consultation_types": {
            "presentiel": presentiel_count,
            "online": online_count,
            "total": presentiel_count + online_count,
        },
        
        "revenue": {
            "total_earned": float(rev.total_revenue),
            "pending_payment": float(rev.pending_revenue),
            "potential_total": float(rev.potential_revenue),
            "average_fee": round(float(rev.avg_fee), 2),
            "currency": doctor.currency or "TND",
        },
        
        "monthly_trends": monthly_data,
        
        "today": {
            "total": today.total,
            "completed": today.completed,
            "confirmed": today.confirmed,
            "pending": today.pending,
            "cancelled": today.cancelled,
            "online": today.online,
            "presentiel": today.presentiel,
        },
        
        "weekly_trend": daily_data,
        "peak_hours": peak_hours,
        "top_patients": top_patients,
    }


# ================================================================
# PDF REPORT GENERATION
# ================================================================
import base64
import os

PERIOD_LABELS = {
    "week": "Derniers 7 jours",
    "month": "Derniers 30 jours",
    "3months": "Derniers 3 mois",
    "6months": "Derniers 6 mois",
    "year": "Dernière année",
    "all": "Depuis le début",
}

_LOGO_B64_CACHE: str | None = None

def _get_logo_b64() -> str:
    """Read the logo file and return as base64 data URI (cached)."""
    global _LOGO_B64_CACHE
    if _LOGO_B64_CACHE:
        return _LOGO_B64_CACHE
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", "logo.png")
    try:
        with open(logo_path, "rb") as f:
            raw = f.read()
        _LOGO_B64_CACHE = f"data:image/png;base64,{base64.b64encode(raw).decode()}"
    except Exception:
        _LOGO_B64_CACHE = ""
    return _LOGO_B64_CACHE


def _build_pdf_html(doctor, stats: dict) -> str:
    """Build a premium PDF report (xhtml2pdf-compatible: tables, no flexbox)."""
    now = datetime.utcnow()
    o = stats["overview"]
    rev = stats["revenue"]
    ct = stats["consultation_types"]
    monthly = stats["monthly_trends"]
    today_data = stats["today"]
    weekly = stats["weekly_trend"]
    peak = stats.get("peak_hours", [])
    top_pts = stats.get("top_patients", [])
    period_label = PERIOD_LABELS.get(stats["period"], stats["period"])
    ref = f"RPT-{now.strftime('%Y%m%d')}-{abs(id(stats)) % 100000:05d}"
    logo_uri = _get_logo_b64()
    currency = rev["currency"]

    def pct(v, t):
        return f"{(v/t*100):.1f}" if t > 0 else "0.0"

    # Monthly rows
    m_rows = ""
    for m in monthly:
        m_rows += f"""<tr>
            <td style="font-weight:bold;">{m['month']} {m['year']}</td>
            <td style="text-align:center;">{m['total']}</td>
            <td style="text-align:center;color:#059669;">{m['completed']}</td>
            <td style="text-align:center;color:#DC2626;">{m['cancelled']}</td>
            <td style="text-align:right;font-weight:bold;">{m['revenue']:.2f} {currency}</td>
        </tr>"""

    # Weekly rows
    w_rows = "".join(f"<tr><td>{d['day']}</td><td style='text-align:center;font-weight:bold;'>{d['count']}</td></tr>" for d in weekly)

    # Peak hours
    pk_rows = "".join(f"<tr><td>{h['hour']:02d}:00 - {h['hour']:02d}:59</td><td style='text-align:center;font-weight:bold;'>{h['count']}</td></tr>" for h in peak)

    # Top patients
    tp_rows = "".join(f"<tr><td style='text-align:center;font-weight:bold;color:#7C3AED;'>#{i+1}</td><td>{p['name']}</td><td style='text-align:center;font-weight:bold;'>{p['visit_count']}</td></tr>" for i, p in enumerate(top_pts))

    doctor_name = f"{doctor.first_name} {doctor.last_name}"
    specialty = doctor.specialty or ""
    addr = ", ".join(filter(None, [doctor.cabinet_address, doctor.cabinet_city]))

    logo_img = f'<img src="{logo_uri}" width="80" height="80" />' if logo_uri else ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<style>
    @page {{
        size: A4;
        margin: 1.5cm;
    }}
    body {{
        font-family: Helvetica, Arial, sans-serif;
        color: #1F2937;
        font-size: 9px;
        line-height: 1.5;
    }}
    h1 {{
        font-size: 20px;
        margin: 4px 0 0 0;
        color: #ffffff;
    }}
    h2 {{
        font-size: 12px;
        color: #111827;
        margin: 14px 0 6px 0;
        padding-bottom: 3px;
        border-bottom: 2px solid #D1D5DB;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
    }}
    th {{
        background-color: #F3F4F6;
        padding: 6px 8px;
        text-align: left;
        font-size: 8px;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        color: #374151;
        border-bottom: 2px solid #D1D5DB;
    }}
    td {{
        padding: 5px 8px;
        border-bottom: 1px solid #E5E7EB;
        font-size: 9px;
    }}
</style>
</head>
<body>

<!-- ==================== HEADER ==================== -->
<table style="width:100%;background-color:#1E1B4B;color:#ffffff;padding:0;">
<tr>
    <td style="padding:16px 20px;vertical-align:middle;width:90px;background-color:#1E1B4B;">
        {logo_img}
    </td>
    <td style="padding:16px 10px;vertical-align:middle;background-color:#1E1B4B;">
        <span style="font-size:16px;font-weight:bold;color:#ffffff;">MediConnect</span><br/>
        <span style="font-size:8px;color:#A5B4FC;text-transform:uppercase;letter-spacing:2px;">Rapport d'Activite Cabinet</span>
    </td>
    <td style="padding:16px 20px;text-align:right;vertical-align:middle;background-color:#1E1B4B;">
        <span style="font-size:8px;color:#C7D2FE;"><b style="color:#ffffff;">Ref:</b> {ref}</span><br/>
        <span style="font-size:8px;color:#C7D2FE;"><b style="color:#ffffff;">Date:</b> {now.strftime("%d/%m/%Y a %H:%M")}</span>
    </td>
</tr>
</table>

<!-- Doctor info bar -->
<table style="width:100%;background-color:#312E81;margin-bottom:14px;">
<tr>
    <td style="padding:10px 20px;background-color:#312E81;">
        <span style="font-size:14px;font-weight:bold;color:#ffffff;">Dr. {doctor_name}</span>
        <span style="font-size:9px;color:#C7D2FE;"> &mdash; {specialty}</span>
        {"<br/><span style='font-size:8px;color:#A5B4FC;'>" + addr + "</span>" if addr else ""}
    </td>
    <td style="padding:10px 20px;text-align:right;background-color:#312E81;">
        <span style="font-size:8px;color:#C7D2FE;">Periode: <b style='color:#ffffff;'>{period_label}</b></span><br/>
        <span style="font-size:7px;background-color:#4338CA;color:#ffffff;padding:2px 8px;font-weight:bold;">RAPPORT CONFIDENTIEL</span>
    </td>
</tr>
</table>

<!-- ==================== KPI CARDS ==================== -->
<h2>Indicateurs Cles de Performance</h2>
<table style="margin-bottom:14px;">
<tr>
    <td style="text-align:center;padding:12px 6px;border:1px solid #E5E7EB;">
        <div style="height:3px;background-color:#8B5CF6;margin-bottom:6px;"></div>
        <span style="font-size:22px;font-weight:bold;color:#111827;">{o['unique_patients']}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;letter-spacing:0.7px;color:#6B7280;font-weight:bold;">Patients Actifs</span><br/>
        <span style="font-size:7px;color:#9CA3AF;">{o['total_appointments']} RDV total</span>
    </td>
    <td style="text-align:center;padding:12px 6px;border:1px solid #E5E7EB;">
        <div style="height:3px;background-color:#059669;margin-bottom:6px;"></div>
        <span style="font-size:22px;font-weight:bold;color:#059669;">{o['completion_rate']}%</span><br/>
        <span style="font-size:7px;text-transform:uppercase;letter-spacing:0.7px;color:#6B7280;font-weight:bold;">Taux Completion</span><br/>
        <span style="font-size:7px;color:#9CA3AF;">{o['completed']} termines</span>
    </td>
    <td style="text-align:center;padding:12px 6px;border:1px solid #E5E7EB;">
        <div style="height:3px;background-color:#D97706;margin-bottom:6px;"></div>
        <span style="font-size:22px;font-weight:bold;color:#D97706;">{rev['total_earned']:.0f}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;letter-spacing:0.7px;color:#6B7280;font-weight:bold;">Revenus ({currency})</span><br/>
        <span style="font-size:7px;color:#9CA3AF;">Moy. {rev['average_fee']:.0f}/cons.</span>
    </td>
    <td style="text-align:center;padding:12px 6px;border:1px solid #E5E7EB;">
        <div style="height:3px;background-color:#DC2626;margin-bottom:6px;"></div>
        <span style="font-size:22px;font-weight:bold;color:#DC2626;">{o['cancellation_rate']}%</span><br/>
        <span style="font-size:7px;text-transform:uppercase;letter-spacing:0.7px;color:#6B7280;font-weight:bold;">Taux Annulation</span><br/>
        <span style="font-size:7px;color:#9CA3AF;">{o['cancelled']} annules</span>
    </td>
</tr>
</table>

<!-- ==================== TODAY ==================== -->
<h2>Resume du Jour &mdash; {now.strftime("%d/%m/%Y")}</h2>
<table style="margin-bottom:14px;">
<tr>
    <td style="text-align:center;padding:10px;border:1px solid #E5E7EB;">
        <span style="font-size:20px;font-weight:bold;">{today_data['total']}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;color:#6B7280;font-weight:bold;">Total</span>
    </td>
    <td style="text-align:center;padding:10px;border:1px solid #E5E7EB;">
        <span style="font-size:20px;font-weight:bold;color:#059669;">{today_data['completed']}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;color:#6B7280;font-weight:bold;">Termines</span>
    </td>
    <td style="text-align:center;padding:10px;border:1px solid #E5E7EB;">
        <span style="font-size:20px;font-weight:bold;color:#2563EB;">{today_data['confirmed']}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;color:#6B7280;font-weight:bold;">Confirmes</span>
    </td>
    <td style="text-align:center;padding:10px;border:1px solid #E5E7EB;">
        <span style="font-size:20px;font-weight:bold;color:#D97706;">{today_data['pending']}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;color:#6B7280;font-weight:bold;">En Attente</span>
    </td>
</tr>
</table>

<!-- ==================== STATUS BREAKDOWN ==================== -->
<h2>Repartition des Statuts</h2>
<table>
<thead><tr><th>Statut</th><th style="text-align:center;">Nombre</th><th style="text-align:right;">Pourcentage</th></tr></thead>
<tbody>
<tr><td style="font-weight:bold;color:#059669;">Termines</td><td style="text-align:center;">{o['completed']}</td><td style="text-align:right;">{pct(o['completed'], o['total_appointments'])}%</td></tr>
<tr><td style="font-weight:bold;color:#2563EB;">Confirmes</td><td style="text-align:center;">{o['confirmed']}</td><td style="text-align:right;">{pct(o['confirmed'], o['total_appointments'])}%</td></tr>
<tr><td style="font-weight:bold;color:#D97706;">En attente</td><td style="text-align:center;">{o['pending']}</td><td style="text-align:right;">{pct(o['pending'], o['total_appointments'])}%</td></tr>
<tr><td style="font-weight:bold;color:#DC2626;">Annules</td><td style="text-align:center;">{o['cancelled']}</td><td style="text-align:right;">{pct(o['cancelled'], o['total_appointments'])}%</td></tr>
<tr><td style="font-weight:bold;color:#6B7280;">Absents</td><td style="text-align:center;">{o['no_show']}</td><td style="text-align:right;">{pct(o['no_show'], o['total_appointments'])}%</td></tr>
<tr><td style="font-weight:bold;color:#7C3AED;">Reportes</td><td style="text-align:center;">{o['rescheduled']}</td><td style="text-align:right;">{pct(o['rescheduled'], o['total_appointments'])}%</td></tr>
</tbody>
</table>

<!-- ==================== MONTHLY TRENDS ==================== -->
{"<h2>Evolution Mensuelle</h2><table><thead><tr><th>Mois</th><th style='text-align:center;'>Total</th><th style='text-align:center;'>Termines</th><th style='text-align:center;'>Annules</th><th style='text-align:right;'>Revenu (" + currency + ")</th></tr></thead><tbody>" + m_rows + "</tbody></table>" if monthly else ""}

<!-- ==================== FINANCES ==================== -->
<h2>Details Financiers</h2>
<table>
<tbody>
<tr><td style="font-weight:bold;">Revenus Percus</td><td style="text-align:right;font-weight:bold;color:#059669;">{rev['total_earned']:.2f} {currency}</td></tr>
<tr><td style="font-weight:bold;">Paiements en Attente</td><td style="text-align:right;font-weight:bold;color:#D97706;">{rev['pending_payment']:.2f} {currency}</td></tr>
<tr><td style="font-weight:bold;">Revenu Potentiel</td><td style="text-align:right;font-weight:bold;color:#2563EB;">{rev['potential_total']:.2f} {currency}</td></tr>
<tr><td style="font-weight:bold;">Frais Moyen / Consultation</td><td style="text-align:right;font-weight:bold;color:#7C3AED;">{rev['average_fee']:.2f} {currency}</td></tr>
</tbody>
</table>

<!-- ==================== CONSULTATION TYPE ==================== -->
<h2>Types de Consultation</h2>
<table style="margin-bottom:14px;">
<tr>
    <td style="text-align:center;padding:10px;border:1px solid #E5E7EB;">
        <span style="font-size:20px;font-weight:bold;color:#7C3AED;">{ct['presentiel']}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;color:#6B7280;font-weight:bold;">Presentiel</span>
    </td>
    <td style="text-align:center;padding:10px;border:1px solid #E5E7EB;">
        <span style="font-size:20px;font-weight:bold;color:#0891B2;">{ct['online']}</span><br/>
        <span style="font-size:7px;text-transform:uppercase;color:#6B7280;font-weight:bold;">En Ligne</span>
    </td>
</tr>
</table>

<!-- ==================== WEEKLY ==================== -->
{"<h2>Activite Hebdomadaire</h2><table><thead><tr><th>Jour</th><th style='text-align:center;'>Nombre de RDV</th></tr></thead><tbody>" + w_rows + "</tbody></table>" if w_rows else ""}

<!-- ==================== PEAK HOURS ==================== -->
{"<h2>Heures de Pointe</h2><table><thead><tr><th>Creneau Horaire</th><th style='text-align:center;'>Nombre de RDV</th></tr></thead><tbody>" + pk_rows + "</tbody></table>" if peak else ""}

<!-- ==================== TOP PATIENTS ==================== -->
{"<h2>Patients les Plus Fideles</h2><table><thead><tr><th style='text-align:center;'>#</th><th>Patient</th><th style='text-align:center;'>Nombre de Visites</th></tr></thead><tbody>" + tp_rows + "</tbody></table>" if top_pts else ""}

<!-- ==================== GLOBAL SUMMARY ==================== -->
<h2>Synthese Globale</h2>
<table>
<tbody>
<tr><td>Total des Rendez-vous</td><td style="text-align:right;font-weight:bold;">{o['total_appointments']}</td></tr>
<tr><td>Patients Uniques</td><td style="text-align:right;font-weight:bold;">{o['unique_patients']}</td></tr>
<tr><td>Taux de Completion</td><td style="text-align:right;font-weight:bold;color:#059669;">{o['completion_rate']}%</td></tr>
<tr><td>Taux d'Annulation</td><td style="text-align:right;font-weight:bold;color:#DC2626;">{o['cancellation_rate']}%</td></tr>
<tr><td>Taux d'Absence</td><td style="text-align:right;font-weight:bold;color:#6B7280;">{o['no_show_rate']}%</td></tr>
<tr><td>Chiffre d'Affaires Total</td><td style="text-align:right;font-weight:bold;color:#D97706;">{rev['total_earned']:.2f} {currency}</td></tr>
</tbody>
</table>

<!-- ==================== FOOTER ==================== -->
<br/>
<table style="width:100%;border-top:2px solid #E5E7EB;">
<tr>
    <td style="text-align:center;padding:10px 0;font-size:7px;color:#9CA3AF;">
        <span style="font-size:11px;font-weight:bold;color:#4338CA;">MediConnect</span><br/>
        Rapport genere automatiquement par MediConnect &mdash; Plateforme Medicale Intelligente<br/>
        Ce document est confidentiel et destine a un usage professionnel uniquement.<br/>
        &copy; {now.year} MediConnect &mdash; Ref: {ref}
    </td>
</tr>
</table>

</body>
</html>"""



@router.get("/report/download")
async def download_pdf_report(
    period: str = "all",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate and download a PDF report of cabinet statistics."""
    stats_data = await get_dashboard_statistics(
        period=period, current_user=current_user, db=db,
    )
    doctor = await get_doctor_from_user(db, current_user)
    html = _build_pdf_html(doctor, stats_data)

    from xhtml2pdf import pisa
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

    if pisa_status.err:
        raise HTTPException(status_code=500, detail="Failed to generate PDF report")

    pdf_buffer.seek(0)
    now = datetime.utcnow()
    filename = f"rapport_cabinet_{now.strftime('%Y%m%d_%H%M')}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

