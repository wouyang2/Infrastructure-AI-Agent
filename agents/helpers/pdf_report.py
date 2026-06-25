from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any


def build_inspection_pdf(report: dict[str, Any], rendered_report: str = "") -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            Image,
            KeepTogether,
            ListFlowable,
            ListItem,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError(
            "PDF export requires reportlab. Install project requirements first."
        ) from exc

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="Infrastructure Inspection Report",
    )
    styles = _styles()
    story: list[Any] = []

    case = report.get("case", {})
    asset = case.get("asset", {})
    severity = report.get("severity", {})
    plan = report.get("maintenance_plan", {})
    schedule = report.get("schedule")
    observations = report.get("observations", [])
    citations = severity.get("citations", [])
    precedents = plan.get("historical_precedents", [])

    story.extend(
        [
            Paragraph("Infrastructure Inspection Report", styles["Title"]),
            Paragraph(
                _line(
                    asset.get("name", "Unknown asset"),
                    asset.get("asset_type", "asset"),
                    case.get("case_id", "Unknown case"),
                ),
                styles["Subtitle"],
            ),
            Spacer(1, 0.16 * inch),
            _summary_table(report, styles),
            Spacer(1, 0.18 * inch),
        ]
    )

    story.extend(
        _section(
            "Executive Summary",
            [
                Paragraph(_key_value("Location", asset.get("location", "Unknown")), styles["Body"]),
                Paragraph(_key_value("Criticality", asset.get("criticality", "unknown")), styles["Body"]),
                Paragraph(_key_value("Recommended action", plan.get("recommended_action", "None")), styles["Body"]),
                Paragraph(_key_value("Estimated duration", f"{plan.get('estimated_duration_hours', 0)} hours"), styles["Body"]),
                Paragraph(_clean_text(severity.get("rationale", "")), styles["Body"]),
            ],
            styles,
        )
    )

    if rendered_report:
        narrative = _narrative_paragraphs(rendered_report)
        if narrative:
            story.extend(
                _section(
                    "Supervisor Narrative",
                    [Paragraph(paragraph, styles["Body"]) for paragraph in narrative[:5]],
                    styles,
                )
            )

    story.extend(
        _section(
            "Observed Conditions",
            [
                _table(
                    [["ID", "Defect", "Source", "Confidence", "Description"]]
                    + [
                        [
                            observation.get("observation_id", ""),
                            _human(observation.get("defect_type", "")),
                            observation.get("source_modality", ""),
                            f"{float(observation.get('confidence', 0)):.0%}",
                            _clean_text(observation.get("description", "")),
                        ]
                        for observation in observations
                    ],
                    [0.7 * inch, 0.9 * inch, 0.7 * inch, 0.8 * inch, 3.6 * inch],
                    styles,
                )
            ],
            styles,
        )
    )

    story.extend(
        _section(
            "Guidance And Repair Precedents",
            [
                Paragraph("Retrieved Guidance", styles["Label"]),
                _bullet_list(
                    [
                        f"{citation.get('title', 'Untitled')} [{citation.get('document_id', '')}]"
                        for citation in citations
                    ]
                    or ["No strongly matched guidance was retrieved."],
                    styles,
                ),
                Spacer(1, 0.06 * inch),
                Paragraph("Historical Repairs", styles["Label"]),
                _bullet_list(
                    [
                        (
                            f"{precedent.get('title', 'Untitled')} "
                            f"[{precedent.get('document_id', '')}] - "
                            f"{precedent.get('repair_method', '')}; "
                            f"outcome: {precedent.get('outcome', '')}"
                        )
                        for precedent in precedents
                    ]
                    or ["No comparable historical repairs were found."],
                    styles,
                ),
            ],
            styles,
        )
    )

    story.extend(
        _section(
            "Maintenance Plan",
            [
                _table(
                    [["Task", "Description", "Hours"]]
                    + [
                        [
                            task.get("name", ""),
                            _clean_text(task.get("description", "")),
                            task.get("estimated_hours", ""),
                        ]
                        for task in plan.get("tasks", [])
                    ],
                    [1.35 * inch, 4.6 * inch, 0.65 * inch],
                    styles,
                ),
                Spacer(1, 0.08 * inch),
                Paragraph(_key_value("Materials", ", ".join(plan.get("materials", [])) or "None listed"), styles["Body"]),
                Paragraph(_key_value("Equipment", ", ".join(plan.get("equipment", [])) or "None listed"), styles["Body"]),
                Paragraph(_key_value("Permits", ", ".join(plan.get("permits", [])) or "None listed"), styles["Body"]),
                Paragraph("Risks", styles["Label"]),
                _bullet_list(plan.get("risks", []) or ["No risks listed."], styles),
            ],
            styles,
        )
    )

    story.extend(_schedule_section(schedule, styles))
    story.extend(_image_section(report.get("annotated_media_paths", []), styles))

    def add_footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        page_width, page_height = letter
        canvas.setFillColor(colors.white)
        canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(0.65 * inch, 0.34 * inch, "Infrastructure AI Agent")
        canvas.drawRightString(7.85 * inch, 0.34 * inch, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    return buffer.getvalue()


def _styles() -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#111827"),
            spaceAfter=8,
        ),
        "Subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["BodyText"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569"),
        ),
        "Heading": ParagraphStyle(
            "ReportHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "Body": ParagraphStyle(
            "ReportBody",
            parent=base["BodyText"],
            fontSize=9,
            leading=12.5,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=5,
        ),
        "Small": ParagraphStyle(
            "ReportSmall",
            parent=base["BodyText"],
            fontSize=7.8,
            leading=10,
            textColor=colors.HexColor("#1F2937"),
        ),
        "Label": ParagraphStyle(
            "ReportLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#334155"),
            spaceBefore=4,
            spaceAfter=3,
        ),
    }


def _summary_table(report: dict[str, Any], styles: dict[str, Any]) -> Any:
    severity = report.get("severity", {})
    plan = report.get("maintenance_plan", {})
    schedule = report.get("schedule")
    rows = [
        ["Severity", _human(severity.get("severity", "unknown"))],
        ["Urgency", _human(severity.get("urgency", "unknown"))],
        ["Repair", "Required" if severity.get("repair_required") else "Monitor"],
        ["Schedule", _window_text(schedule) if schedule else "No repair window required"],
        ["Action", plan.get("recommended_action", "None")],
    ]
    return _table(rows, [1.25 * 72, 5.25 * 72], styles, header=False)


def _section(title: str, flowables: list[Any], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import KeepTogether, Paragraph

    return [KeepTogether([Paragraph(title, styles["Heading"]), *flowables])]


def _schedule_section(schedule: dict[str, Any] | None, styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Paragraph

    if not schedule:
        return _section(
            "Repair Schedule",
            [Paragraph("No repair window is required. Continue monitoring.", styles["Body"])],
            styles,
        )
    return _section(
        "Repair Schedule",
        [
            _table(
                [
                    ["Recommended window", _window_text(schedule)],
                    ["Disruption score", schedule.get("disruption_score", "")],
                    ["Context risk score", schedule.get("context_risk_score", "")],
                    ["Total score", schedule.get("total_score", "")],
                ],
                [1.6 * 72, 4.9 * 72],
                styles,
                header=False,
            ),
            Paragraph("Context", styles["Label"]),
            _bullet_list(schedule.get("context_summary", []) or ["No context summary."], styles),
            Paragraph("Tradeoffs", styles["Label"]),
            _bullet_list(schedule.get("tradeoffs", []) or ["No tradeoffs listed."], styles),
        ],
        styles,
    )


def _image_section(paths: list[str], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Image, PageBreak, Paragraph, Spacer

    valid_paths = [Path(path) for path in paths if Path(path).exists()]
    if not valid_paths:
        return []

    flowables: list[Any] = [PageBreak(), Paragraph("Annotated Evidence", styles["Heading"])]
    for path in valid_paths[:4]:
        flowables.append(Paragraph(path.name, styles["Label"]))
        flowables.append(Image(str(path), width=6.4 * 72, height=3.8 * 72, kind="proportional"))
        flowables.append(Spacer(1, 0.12 * 72))
    return flowables


def _table(
    rows: list[list[Any]],
    widths: list[float],
    styles: dict[str, Any],
    *,
    header: bool = True,
) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    safe_rows = [
        [Paragraph(_clean_text(cell), styles["Small"]) for cell in row]
        for row in rows
    ]
    table = Table(safe_rows, colWidths=widths, hAlign="LEFT", repeatRows=1 if header else 0)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
            ]
        )
    else:
        commands.append(("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")))
    table.setStyle(TableStyle(commands))
    return table


def _bullet_list(items: list[str], styles: dict[str, Any]) -> Any:
    from reportlab.platypus import ListFlowable, ListItem, Paragraph

    return ListFlowable(
        [
            ListItem(Paragraph(_clean_text(item), styles["Body"]), leftIndent=10)
            for item in items
        ],
        bulletType="bullet",
        start="circle",
        leftIndent=14,
    )


def _window_text(schedule: dict[str, Any]) -> str:
    window = schedule.get("recommended_window", {})
    return _line(window.get("start", ""), window.get("end", ""), separator=" to ")


def _key_value(label: str, value: Any) -> str:
    return f"<b>{_clean_text(label)}:</b> {_clean_text(value)}"


def _line(*parts: Any, separator: str = " - ") -> str:
    return separator.join(_clean_text(part) for part in parts if part not in (None, ""))


def _human(value: Any) -> str:
    text = str(value or "unknown").replace("_", " ")
    return text[:1].upper() + text[1:]


def _narrative_paragraphs(text: str) -> list[str]:
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    lines = []
    for line in cleaned.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = re.sub(r"^\s*\d+\.\s+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = line.strip()
        if line and not re.match(r"^[-=_]{3,}$", line):
            lines.append(_clean_text(line))
    return lines


def _clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\s+", " ", text).strip()
