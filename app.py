
import io
import re
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st


# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="WhatsApp Daily Report Automation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CONSTANTS
# ============================================================
TARGET_COLUMNS = [
    "S.No",
    "Reporting Date",
    "Ticket No",
    "Start Date",
    "End Date",
    "Project Site",
    "Activities",
    "KE Representative",
    "Vendor Supervisor",
    "Manpower (Labour)",
]

DEDUP_COLUMNS = [
    "Reporting Date",
    "Ticket No",
    "Start Date",
    "End Date",
    "Project Site",
    "Activities",
    "KE Representative",
    "Vendor Supervisor",
    "Manpower (Labour)",
]

TEXT_COLUMNS = [
    "Ticket No",
    "Project Site",
    "Activities",
    "KE Representative",
    "Vendor Supervisor",
]

DATE_COLUMNS = ["Reporting Date", "Start Date", "End Date"]


# ============================================================
# STYLING
# ============================================================
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }

    .sub-title {
        color: #666;
        margin-bottom: 1.5rem;
    }

    .section-title {
        font-size: 1.45rem;
        font-weight: 700;
        margin-top: 1.2rem;
        margin-bottom: 0.8rem;
    }

    .info-box {
        padding: 12px 16px;
        border-radius: 8px;
        background: #f4f7fb;
        border: 1px solid #dce4ef;
        margin-bottom: 10px;
    }

    .date-help {
        color: #555;
        font-size: 0.9rem;
        margin-top: -8px;
        margin-bottom: 8px;
    }

    div[data-testid="stMetric"] {
        border: 1px solid #e1e5eb;
        padding: 12px;
        border-radius: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def clean_text(value):
    """Convert a cell/value to clean text."""
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "nat", "none"}:
        return ""

    return re.sub(r"\s+", " ", text).strip()


def parse_date_value(value, default_year=None, default_month=None):
    """Safely parse Excel/WhatsApp dates, including ordinal and day-only dates."""
    if default_year is None:
        default_year = date.today().year

    if value is None:
        return pd.NaT
    try:
        if pd.isna(value):
            return pd.NaT
    except (TypeError, ValueError):
        pass

    if isinstance(value, pd.Timestamp):
        return pd.NaT if pd.isna(value) else value.normalize()
    if isinstance(value, datetime):
        return pd.Timestamp(value).normalize()
    if isinstance(value, date):
        return pd.Timestamp(value).normalize()

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
            if 20000 <= number <= 60000:
                parsed = pd.to_datetime(number, unit="D", origin="1899-12-30", errors="coerce")
                return pd.NaT if pd.isna(parsed) else pd.Timestamp(parsed).normalize()
        except (TypeError, ValueError, OverflowError):
            return pd.NaT

    text = clean_text(value)
    if not text:
        return pd.NaT

    text = text.replace(",", " ")
    text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()

    month_map = {
        "january": 1, "jan": 1, "february": 2, "feb": 2,
        "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
        "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
        "november": 11, "nov": 11, "december": 12, "dec": 12,
    }

    # Day-only dates such as "12th" use the WhatsApp message month/year.
    m = re.fullmatch(r"(\d{1,2})", text)
    if m and default_month is not None:
        try:
            return pd.Timestamp(year=int(default_year), month=int(default_month), day=int(m.group(1))).normalize()
        except (ValueError, TypeError, OverflowError):
            return pd.NaT

    # 11 September / 11 September 2026
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{2,4}))?", text)
    if m:
        month = month_map.get(m.group(2).lower())
        if month is not None:
            year = int(m.group(3)) if m.group(3) else int(default_year)
            if year < 100:
                year += 2000
            try:
                return pd.Timestamp(year=year, month=month, day=int(m.group(1))).normalize()
            except (ValueError, TypeError, OverflowError):
                return pd.NaT

    for fmt in ["%d.%m.%y", "%d.%m.%Y", "%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y"]:
        try:
            return pd.Timestamp(datetime.strptime(text, fmt)).normalize()
        except (ValueError, TypeError):
            pass

    try:
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
        if pd.notna(parsed):
            return pd.Timestamp(parsed).normalize()
    except (ValueError, TypeError, OverflowError):
        pass

    # Handle explanatory text such as "work completed today 10-09-2026".
    for pattern in [
        r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b",
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\b",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date_value(match.group(0), default_year=default_year, default_month=default_month)
            if pd.notna(parsed):
                return parsed

    return pd.NaT

def normalize_datetime_series(series):
    """Convert a Series to datetime64 safely, preserving invalid values as NaT."""
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def parse_manpower(value):
    """Extract numeric manpower from values such as 2nos, 3 Nos, 4, etc."""
    if value is None:
        return pd.NA

    text = clean_text(value)
    if not text:
        return pd.NA

    # First numeric occurrence.
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return pd.NA

    try:
        number = float(match.group())
        if number.is_integer():
            return int(number)
        return number
    except Exception:
        return pd.NA


def normalize_column_name(name):
    """Normalize Excel/header names for matching."""
    text = clean_text(name).lower()
    text = text.replace(".", "")
    text = re.sub(r"[\s_\-]+", " ", text).strip()
    return text


def standardize_dataframe(df):
    """
    Convert any dataframe into the application's target schema.
    """
    df = df.copy()

    # Remove completely empty rows/columns.
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")

    if df.empty:
        return pd.DataFrame(columns=TARGET_COLUMNS)

    # Map normalized names to original names.
    normalized = {
        normalize_column_name(col): col
        for col in df.columns
    }

    aliases = {
        "S.No": [
            "s no",
            "s.no",
            "serial no",
            "serial number",
            "sr no",
        ],
        "Reporting Date": [
            "reporting date",
            "report date",
            "date of report",
            "reporting dt",
        ],
        "Ticket No": [
            "ticket no",
            "ticket number",
            "ticket",
        ],
        "Start Date": [
            "start date",
            "star date",   # source typo handled
            "start",
        ],
        "End Date": [
            "end date",
            "end",
        ],
        "Project Site": [
            "project site",
            "site",
            "project",
        ],
        "Activities": [
            "activities",
            "activity",
            "work activity",
        ],
        "KE Representative": [
            "ke representative",
            "ke supervisor",
            "ke rep",
            "ke representative name",
        ],
        "Vendor Supervisor": [
            "vendor supervisor",
            "vendor sup",
            "vendor representative",
        ],
        "Manpower (Labour)": [
            "manpower (labour)",
            "manpower labour",
            "manpower",
            "labour",
            "labor",
            "manpower nos",
        ],
    }

    result = pd.DataFrame(index=df.index)

    for target in TARGET_COLUMNS:
        if target == "S.No":
            result[target] = pd.NA
            continue

        source_col = None

        # Exact normalized match first.
        for alias in aliases.get(target, []):
            alias_norm = normalize_column_name(alias)
            if alias_norm in normalized:
                source_col = normalized[alias_norm]
                break

        if source_col is not None:
            result[target] = df[source_col]
        else:
            result[target] = pd.NA

    # Clean text columns.
    for col in TEXT_COLUMNS:
        result[col] = result[col].apply(clean_text)

    # Parse dates.
    for col in DATE_COLUMNS:
        result[col] = result[col].apply(parse_date_value)

    # Parse manpower.
    result["Manpower (Labour)"] = result["Manpower (Labour)"].apply(
        parse_manpower
    )

    return result[TARGET_COLUMNS]


def find_header_row(raw_df):
    """Find row containing Ticket No in an uploaded Excel sheet."""
    for idx in range(min(len(raw_df), 30)):
        row_values = [
            normalize_column_name(x)
            for x in raw_df.iloc[idx].tolist()
        ]

        if any(
            value in {"ticket no", "ticket number", "ticket"}
            for value in row_values
        ):
            return idx

    return None


def read_excel_file(uploaded_file):
    """Read the first worksheet and detect its header row."""
    try:
        file_bytes = uploaded_file.getvalue()

        raw = pd.read_excel(
            io.BytesIO(file_bytes),
            sheet_name=0,
            header=None,
        )

        if raw.empty:
            return pd.DataFrame(columns=TARGET_COLUMNS), "The Excel file is empty."

        header_row = find_header_row(raw)

        if header_row is None:
            # Try assuming first row is the header.
            df = pd.read_excel(
                io.BytesIO(file_bytes),
                sheet_name=0,
                header=0,
            )
        else:
            df = pd.read_excel(
                io.BytesIO(file_bytes),
                sheet_name=0,
                header=header_row,
            )

        standardized = standardize_dataframe(df)

        # Remove rows without Ticket No.
        standardized["Ticket No"] = standardized["Ticket No"].apply(clean_text)
        standardized = standardized[
            standardized["Ticket No"] != ""
        ].copy()

        return standardized, None

    except Exception as exc:
        return pd.DataFrame(columns=TARGET_COLUMNS), str(exc)


# ============================================================
# WHATSAPP PARSER
# ============================================================
def split_whatsapp_blocks(text):
    """Split WhatsApp text into blocks using only valid Ticket No + number lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    ticket_pattern = re.compile(r"\bTicket\s*No\.?\s*[:\-]?\s*([A-Za-z]*\d+)\b", re.IGNORECASE)
    blocks, current = [], []

    for raw_line in text.splitlines():
        if ticket_pattern.search(raw_line):
            if current:
                blocks.append("\n".join(current).strip())
            current = [raw_line]
        elif current:
            current.append(raw_line)

    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def extract_whatsapp_fields_from_line(line):
    """Extract fields from one line, including multiple fields on one line."""
    field_pattern = re.compile(
        r"(Start\s*Date|Star\s*Date|End\s*Date|Project\s*Site|Project|"
        r"Activit(?:y|ies)|KE\s*(?:Supervisor|Super|Sup|Representative)|"
        r"Vendor\s*Supervisor|Vendor|Manpower(?:\s*\(\s*Labour\s*\))?)"
        r"\s*[:.\-;]*\s*", re.IGNORECASE
    )

    # Ignore ordinary conversation containing words like "activity" or "ticket details".
    if not re.match(
        r"^\s*\*?\s*(?:Start\s*Date|Star\s*Date|End\s*Date|Project\s*Site|Project|"
        r"Activit(?:y|ies)|KE\s*(?:Supervisor|Super|Sup|Representative)|"
        r"Vendor(?:\s*Supervisor)?|Manpower)",
        line, flags=re.IGNORECASE
    ):
        return []

    matches = list(field_pattern.finditer(line))
    fields = []
    for i, match in enumerate(matches):
        label = re.sub(r"\s+", " ", match.group(1).strip()).lower()
        if label.startswith("start") or label.startswith("star date"):
            key = "Start Date"
        elif label.startswith("end"):
            key = "End Date"
        elif label.startswith("project site") or label == "project":
            key = "Project Site"
        elif label.startswith("activ"):
            key = "Activities"
        elif label.startswith("ke "):
            key = "KE Representative"
        elif label.startswith("vendor"):
            key = "Vendor Supervisor"
        elif label.startswith("manpower"):
            key = "Manpower (Labour)"
        else:
            continue

        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        value = line[match.end():value_end]
        value = re.sub(r"^[\s*;:.-]+", "", value)
        value = re.sub(r"\s*<This message was edited>\s*$", "", value, flags=re.IGNORECASE)
        fields.append((key, clean_text(value)))
    return fields


def parse_whatsapp_text(text):
    """Parse tolerant WhatsApp activity records, including timestamp-prefixed tickets."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    ticket_pattern = re.compile(r"\bTicket\s*No\.?\s*[:\-]?\s*([A-Za-z]*\d+)\b", re.IGNORECASE)
    lines = text.splitlines()
    records, current = [], None
    pending_fields, current_message_date = {}, None

    for raw_line in lines:
        ts = re.match(r"^\s*(\d{1,2}/\d{1,2}/\d{4}),\s+\d{1,2}:\d{2}\s+-\s+", raw_line)
        if ts:
            current_message_date = pd.to_datetime(ts.group(1), dayfirst=True, errors="coerce")

        line = re.sub(
            r"^\s*\d{1,2}/\d{1,2}/\d{4},\s+\d{1,2}:\d{2}\s+-\s+[^:]+:\s*",
            "", raw_line
        ).strip()

        tm = ticket_pattern.search(line)
        if tm:
            if current is not None:
                records.append(current)
            current = {
                "S.No": pd.NA,
                "Reporting Date": current_message_date,
                "Ticket No": tm.group(1).upper(),
                "Start Date": "",
                "End Date": "",
                "Project Site": "",
                "Activities": "",
                "KE Representative": "",
                "Vendor Supervisor": "",
                "Manpower (Labour)": "",
                "_message_date": current_message_date,
            }
            for key, value in pending_fields.items():
                if value:
                    current[key] = value
            pending_fields = {}
            line = line[tm.end():].strip()

        if not line:
            continue

        for key, value in extract_whatsapp_fields_from_line(line):
            if current is None:
                if value:
                    pending_fields[key] = value
            elif value or not current.get(key):
                current[key] = value

    if current is not None:
        records.append(current)

    if not records:
        return pd.DataFrame(columns=TARGET_COLUMNS)

    result = pd.DataFrame(records)

    def contextual_date(row, column):
        msg_date = row.get("_message_date")
        if pd.notna(msg_date):
            year, month = int(msg_date.year), int(msg_date.month)
        else:
            year, month = date.today().year, None
        return parse_date_value(row.get(column), default_year=year, default_month=month)

    result["Start Date"] = result.apply(lambda r: contextual_date(r, "Start Date"), axis=1)
    result["End Date"] = result.apply(lambda r: contextual_date(r, "End Date"), axis=1)
    result["Manpower (Labour)"] = result["Manpower (Labour)"].apply(parse_manpower)
    result["KE Representative"] = result["KE Representative"].apply(
        lambda v: "" if clean_text(v).lower() in {"yes", "no", "y", "n", "ok", "available"} else clean_text(v)
    )
    result = result.drop(columns=["_message_date"], errors="ignore")
    return standardize_dataframe(result)


# ============================================================
# MERGE / CLEAN / FILTER
# ============================================================
def remove_exact_duplicates(df):
    """Remove exact duplicates using all operational identifying fields."""
    df = df.copy()

    if df.empty:
        return df

    # Normalize comparison fields.
    for col in TEXT_COLUMNS:
        df[col] = df[col].apply(clean_text)

    for col in DATE_COLUMNS:
        df[col] = normalize_datetime_series(df[col])

    df["Manpower (Labour)"] = df["Manpower (Labour)"].apply(
        parse_manpower
    )

    # Exact duplicate definition deliberately does NOT use Ticket No alone.
    df = df.drop_duplicates(
        subset=DEDUP_COLUMNS,
        keep="first",
    ).copy()

    return df


def sort_report(df):
    """Sort final report chronologically by Start Date, End Date and Ticket No."""
    if df.empty:
        return df.copy()
    result = df.copy()
    result["Start Date"] = normalize_datetime_series(result["Start Date"])
    result["End Date"] = normalize_datetime_series(result["End Date"])
    result["_TicketSort"] = result["Ticket No"].apply(clean_text)
    result["Reporting Date"] = normalize_datetime_series(result["Reporting Date"])
    result = result.sort_values(
        by=["Start Date", "End Date", "Reporting Date", "_TicketSort"],
        ascending=[True, True, True, True],
        na_position="last",
        kind="stable",
    ).drop(columns=["_TicketSort"])
    result["S.No"] = range(1, len(result) + 1)
    return result.reset_index(drop=True)


def filter_by_date_overlap(df, from_date, to_date):
    """
    Include records whose activity interval overlaps the selected period.

    Example:
        Activity: 05-Sep to 12-Sep
        Selected: 10-Sep to 15-Sep
        => included
    """
    if df.empty:
        return df.copy()

    start = pd.Timestamp(from_date)
    end = pd.Timestamp(to_date)

    temp = df.copy()

    temp["Start Date"] = normalize_datetime_series(temp["Start Date"])

    temp["End Date"] = normalize_datetime_series(temp["End Date"])

    # If End Date is missing, use Start Date as the activity end.
    temp["_FilterEnd"] = temp["End Date"].fillna(temp["Start Date"])

    mask = (
        temp["Start Date"].notna()
        & temp["_FilterEnd"].notna()
        & (temp["Start Date"] <= end)
        & (temp["_FilterEnd"] >= start)
    )

    result = temp.loc[mask].drop(columns=["_FilterEnd"])

    return result.copy()


def filter_by_reporting_date(df, from_date, to_date):
    """Filter records by the date on which the report/message was submitted."""
    if df.empty:
        return df.copy()

    start = pd.Timestamp(from_date)
    end = pd.Timestamp(to_date)
    temp = df.copy()
    temp["Reporting Date"] = normalize_datetime_series(temp["Reporting Date"])

    mask = (
        temp["Reporting Date"].notna()
        & (temp["Reporting Date"] >= start)
        & (temp["Reporting Date"] <= end)
    )
    return temp.loc[mask].copy()


def prepare_for_editor(df):
    """Prepare a clean, editable dataframe."""
    df = df.copy()

    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    # Correct ordering.
    df = df[TARGET_COLUMNS]

    # S.No.
    df["S.No"] = range(1, len(df) + 1)

    # Text.
    for col in TEXT_COLUMNS:
        df[col] = df[col].apply(clean_text)

    # Dates MUST remain datetime64 for DateColumn.
    for col in DATE_COLUMNS:
        df[col] = normalize_datetime_series(df[col])

    # Numeric manpower.
    df["Manpower (Labour)"] = df["Manpower (Labour)"].apply(
        parse_manpower
    )
    df["Manpower (Labour)"] = pd.to_numeric(
        df["Manpower (Labour)"],
        errors="coerce",
    ).astype("Float64")

    return df


def validate_dataframe(df):
    """Create row-level validation status."""
    df = df.copy()

    required = [
        "Ticket No",
        "Start Date",
        "End Date",
        "Project Site",
        "Activities",
        "Manpower (Labour)",
    ]

    status = []

    for _, row in df.iterrows():
        missing = []

        for col in required:
            value = row.get(col)

            if pd.isna(value):
                missing.append(col)
                continue

            if isinstance(value, str) and not value.strip():
                missing.append(col)

        status.append("Complete" if not missing else "Incomplete")

    return pd.Series(status, index=df.index)


def safe_filename_date(d):
    return pd.Timestamp(d).strftime("%d-%m-%Y")


# ============================================================
# EXCEL EXPORT
# ============================================================
def create_excel_report(df, from_date, to_date, reporting_from_date, reporting_to_date):
    """
    Generate a formatted Excel workbook in memory.
    """
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    output = io.BytesIO()

    export_df = df.copy()

    # Final S.No.
    export_df["S.No"] = range(1, len(export_df) + 1)

    # Ensure dates are true dates.
    for col in DATE_COLUMNS:
        export_df[col] = pd.to_datetime(
            export_df[col], errors="coerce"
        )

    # Manpower numeric.
    export_df["Manpower (Labour)"] = pd.to_numeric(
        export_df["Manpower (Labour)"],
        errors="coerce",
    )

    # Keep exact report columns.
    export_df = export_df[TARGET_COLUMNS]

    with pd.ExcelWriter(
        output,
        engine="openpyxl",
        datetime_format="DD-MM-YYYY",
        date_format="DD-MM-YYYY",
    ) as writer:
        export_df.to_excel(
            writer,
            sheet_name="Daily Report",
            index=False,
            startrow=3,
        )

        summary = pd.DataFrame(
            {
                "Metric": [
                    "Activity Period From",
                    "Activity Period To",
                    "Reporting Date From",
                    "Reporting Date To",
                    "Total Tickets",
                    "Complete Records",
                    "Incomplete Records",
                    "Total Manpower",
                ],
                "Value": [
                    pd.Timestamp(from_date).date(),
                    pd.Timestamp(to_date).date(),
                    pd.Timestamp(reporting_from_date).date(),
                    pd.Timestamp(reporting_to_date).date(),
                    len(export_df),
                    int(
                        (
                            validate_dataframe(export_df)
                            == "Complete"
                        ).sum()
                    ),
                    int(
                        (
                            validate_dataframe(export_df)
                            == "Incomplete"
                        ).sum()
                    ),
                    float(
                        pd.to_numeric(
                            export_df["Manpower (Labour)"],
                            errors="coerce",
                        ).fillna(0).sum()
                    ),
                ],
            }
        )

        summary.to_excel(
            writer,
            sheet_name="Summary",
            index=False,
        )

    output.seek(0)

    # Format workbook.
    wb = load_workbook(output)

    ws = wb["Daily Report"]

    # Insert title / report period.
    ws["A1"] = "Daily Site Manpower & Work Progress Summary"
    ws["A2"] = (
        f"Activity Period: {pd.Timestamp(from_date).strftime('%d-%b-%Y')} "
        f"to {pd.Timestamp(to_date).strftime('%d-%b-%Y')} | "
        f"Reporting Date: {pd.Timestamp(reporting_from_date).strftime('%d-%b-%Y')} "
        f"to {pd.Timestamp(reporting_to_date).strftime('%d-%b-%Y')}"
    )

    ws["A1"].font = Font(
        bold=True,
        size=16,
    )
    ws["A2"].font = Font(
        italic=True,
        size=11,
    )

    header_row = 4

    header_fill = PatternFill(
        fill_type="solid",
        fgColor="1F4E78",
    )

    header_font = Font(
        bold=True,
        color="FFFFFF",
    )

    thin = Side(
        style="thin",
        color="D9E1F2",
    )

    for cell in ws[header_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )
        cell.border = Border(
            bottom=thin,
        )

    # Body formatting.
    for row in ws.iter_rows(
        min_row=header_row + 1,
        max_row=ws.max_row,
    ):
        for cell in row:
            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

    # Date formatting for all report date fields.
    for date_col in DATE_COLUMNS:
        col_idx = TARGET_COLUMNS.index(date_col) + 1
        for row in range(header_row + 1, ws.max_row + 1):
            ws.cell(row, col_idx).number_format = "DD-MM-YYYY"

    # Widths.
    widths = {
        "A": 8,
        "B": 16,
        "C": 16,
        "D": 14,
        "E": 14,
        "F": 28,
        "G": 42,
        "H": 24,
        "I": 24,
        "J": 18,
    }

    for col_letter, width in widths.items():
        ws.column_dimensions[col_letter].width = width

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = ws.dimensions

    # Summary sheet.
    ws2 = wb["Summary"]

    ws2["A1"].font = Font(
        bold=True,
        size=15,
    )

    for cell in ws2[1]:
        cell.font = Font(bold=True)

    ws2.column_dimensions["A"].width = 25
    ws2.column_dimensions["B"].width = 25

    # Date formatting on summary values.
    for row in [2, 3]:
        ws2.cell(row, 2).number_format = "DD-MM-YYYY"

    final_output = io.BytesIO()
    wb.save(final_output)
    final_output.seek(0)

    return final_output


# ============================================================
# SESSION STATE
# ============================================================
if "excel_df" not in st.session_state:
    st.session_state.excel_df = pd.DataFrame(columns=TARGET_COLUMNS)

# Keep the two WhatsApp sources separately so BOTH are included:
# 1) uploaded TXT export
# 2) manually pasted messages
if "whatsapp_txt_df" not in st.session_state:
    st.session_state.whatsapp_txt_df = pd.DataFrame(columns=TARGET_COLUMNS)

if "whatsapp_pasted_df" not in st.session_state:
    st.session_state.whatsapp_pasted_df = pd.DataFrame(columns=TARGET_COLUMNS)

# Backward compatibility with an older session state.
if "whatsapp_df" not in st.session_state:
    st.session_state.whatsapp_df = pd.DataFrame(columns=TARGET_COLUMNS)

if "merged_df" not in st.session_state:
    st.session_state.merged_df = pd.DataFrame(columns=TARGET_COLUMNS)

if "filtered_df" not in st.session_state:
    st.session_state.filtered_df = pd.DataFrame(columns=TARGET_COLUMNS)

if "last_excel_name" not in st.session_state:
    st.session_state.last_excel_name = ""

if "last_txt_name" not in st.session_state:
    st.session_state.last_txt_name = ""


# ============================================================
# HEADER
# ============================================================
st.markdown(
    '<div class="main-title">📊 WhatsApp Daily Report Automation</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="sub-title">'
    "Merge existing Excel records with WhatsApp site activity reports, "
    "filter by report period, review records, and download a consolidated Excel."
    "</div>",
    unsafe_allow_html=True,
)


# ============================================================
# 1. DATE RANGE
# ============================================================
st.markdown(
    '<div class="section-title">1. Select Report Period</div>',
    unsafe_allow_html=True,
)

today = date.today()

st.write("**Activity Period Filter**")
activity_col1, activity_col2 = st.columns(2)

with activity_col1:
    from_date = st.date_input(
        "Activity From Date",
        value=today,
        format="DD/MM/YYYY",
        key="report_from_date",
    )

with activity_col2:
    to_date = st.date_input(
        "Activity To Date",
        value=today,
        format="DD/MM/YYYY",
        key="report_to_date",
    )

reporting_col1, reporting_col2 = st.columns(2)

with reporting_col1:
    reporting_from_date = st.date_input(
        "Reporting Date From",
        value=from_date,
        format="DD/MM/YYYY",
        key="reporting_from_date",
    )

with reporting_col2:
    reporting_to_date = st.date_input(
        "Reporting Date To",
        value=to_date,
        format="DD/MM/YYYY",
        key="reporting_to_date",
    )

st.markdown(
    '<div class="date-help">'
    "Activity dates filter by work-period overlap. Reporting Date filters by the date "
    "on which the WhatsApp report was submitted. For WhatsApp records, this is taken "
    "from the WhatsApp message date. Existing Excel records must contain a Reporting Date "
    "column to participate in the reporting-date filter."
    "</div>",
    unsafe_allow_html=True,
)

if from_date > to_date:
    st.error("❌ Activity From Date cannot be later than Activity To Date.")
    st.stop()

if reporting_from_date > reporting_to_date:
    st.error("❌ Reporting Date From cannot be later than Reporting Date To.")
    st.stop()

st.success(
    f"Activity period: **{from_date.strftime('%d-%b-%Y')}** to **{to_date.strftime('%d-%b-%Y')}** | "
    f"Reporting dates: **{reporting_from_date.strftime('%d-%b-%Y')}** to "
    f"**{reporting_to_date.strftime('%d-%b-%Y')}**"
)


# ============================================================
# 2. EXISTING EXCEL
# ============================================================
st.markdown(
    '<div class="section-title">2. Upload Existing Excel Report</div>',
    unsafe_allow_html=True,
)

excel_file = st.file_uploader(
    "Upload your existing report Excel",
    type=["xlsx", "xls", "xlsm"],
    key="excel_uploader",
)

if excel_file is not None:
    if excel_file.name != st.session_state.last_excel_name:
        excel_df, excel_error = read_excel_file(excel_file)

        if excel_error:
            st.error(f"Excel reading error: {excel_error}")
        else:
            st.session_state.excel_df = excel_df
            st.session_state.last_excel_name = excel_file.name
            st.success(
                f"Excel loaded successfully: "
                f"**{len(excel_df)} records** found."
            )

if not st.session_state.excel_df.empty:
    st.caption(
        f"Current Excel records: "
        f"{len(st.session_state.excel_df)}"
    )


# ============================================================
# 3. WHATSAPP INPUT
# ============================================================
st.markdown(
    '<div class="section-title">3. Add WhatsApp Report Data</div>',
    unsafe_allow_html=True,
)

st.info(
    "You can use **both WhatsApp sources at the same time**. "
    "Upload a TXT export AND paste additional messages. "
    "The app will combine both sources before removing exact duplicates."
)

# ------------------------------------------------------------
# SOURCE A: WhatsApp TXT export
# ------------------------------------------------------------
st.write("**A. Upload WhatsApp TXT export**")

txt_file = st.file_uploader(
    "Upload WhatsApp TXT export",
    type=["txt"],
    key="txt_uploader",
)

if txt_file is not None:
    # Store the parsed TXT independently from pasted messages.
    if txt_file.name != st.session_state.last_txt_name:
        try:
            whatsapp_text = txt_file.getvalue().decode(
                "utf-8",
                errors="ignore",
            )

            parsed_txt = parse_whatsapp_text(whatsapp_text)

            st.session_state.whatsapp_txt_df = parsed_txt
            st.session_state.last_txt_name = txt_file.name

            st.success(
                f"WhatsApp TXT parsed successfully: "
                f"**{len(parsed_txt)} records** found."
            )
        except Exception as exc:
            st.error(f"WhatsApp TXT parsing error: {exc}")

if not st.session_state.whatsapp_txt_df.empty:
    st.caption(
        f"TXT source records: **{len(st.session_state.whatsapp_txt_df)}**"
    )

    with st.expander("Preview TXT records"):
        st.dataframe(
            prepare_for_editor(st.session_state.whatsapp_txt_df),
            use_container_width=True,
            hide_index=True,
        )

# ------------------------------------------------------------
# SOURCE B: Manually pasted WhatsApp messages
# ------------------------------------------------------------
st.write("**B. Paste additional WhatsApp messages**")

whatsapp_text_input = st.text_area(
    "Paste WhatsApp report text",
    height=240,
    placeholder=(
        "* Ticket No.298662\n"
        "* Start Date 9.9.26\n"
        "* End Date 9.9.26\n"
        "* Project Site Queens road\n"
        "* Activity Paint work\n"
        "* KE Supervisor Zulfiqar\n"
        "* Vendor Supervisor Abdullah\n"
        "* Manpower 2nos"
    ),
    key="whatsapp_paste",
)

parse_col1, parse_col2 = st.columns([1, 5])

with parse_col1:
    parse_button = st.button(
        "Parse Pasted Messages",
        type="primary",
        use_container_width=True,
    )

if parse_button:
    if not whatsapp_text_input.strip():
        st.warning("Please paste WhatsApp messages first.")
    else:
        try:
            parsed_pasted = parse_whatsapp_text(whatsapp_text_input)

            st.session_state.whatsapp_pasted_df = parsed_pasted

            st.success(
                f"Pasted WhatsApp text parsed successfully: "
                f"**{len(parsed_pasted)} records** found."
            )
        except Exception as exc:
            st.error(f"Pasted WhatsApp parsing error: {exc}")

if not st.session_state.whatsapp_pasted_df.empty:
    st.caption(
        f"Pasted source records: "
        f"**{len(st.session_state.whatsapp_pasted_df)}**"
    )

    with st.expander("Preview pasted WhatsApp records"):
        st.dataframe(
            prepare_for_editor(st.session_state.whatsapp_pasted_df),
            use_container_width=True,
            hide_index=True,
        )

# Combined WhatsApp count before merging with Excel.
txt_count = len(st.session_state.whatsapp_txt_df)
pasted_count = len(st.session_state.whatsapp_pasted_df)

if txt_count or pasted_count:
    st.success(
        f"WhatsApp sources ready: **{txt_count} TXT records + "
        f"{pasted_count} pasted records = {txt_count + pasted_count} "
        f"records before duplicate removal.**"
    )

# ============================================================
# 4. MERGE
# ============================================================
st.markdown(
    '<div class="section-title">4. Merge & Filter Records</div>',
    unsafe_allow_html=True,
)

merge_button = st.button(
    "🔄 Merge Excel + WhatsApp Data",
    type="primary",
    use_container_width=True,
)

if merge_button:
    excel_df = st.session_state.excel_df.copy()
    whatsapp_txt_df = st.session_state.whatsapp_txt_df.copy()
    whatsapp_pasted_df = st.session_state.whatsapp_pasted_df.copy()

    pieces = []

    if not excel_df.empty:
        pieces.append(excel_df)

    if not whatsapp_txt_df.empty:
        pieces.append(whatsapp_txt_df)

    if not whatsapp_pasted_df.empty:
        pieces.append(whatsapp_pasted_df)

    if not pieces:
        st.error(
            "Please upload an Excel report and/or add WhatsApp data first."
        )
    else:
        merged = pd.concat(
            pieces,
            ignore_index=True,
        )

        merged = standardize_dataframe(merged)

        # Remove empty ticket rows.
        merged["Ticket No"] = merged["Ticket No"].apply(clean_text)
        merged = merged[
            merged["Ticket No"] != ""
        ].copy()

        before_dedup = len(merged)

        merged = remove_exact_duplicates(merged)

        duplicates_removed = before_dedup - len(merged)

        filtered = filter_by_date_overlap(
            merged,
            from_date,
            to_date,
        )

        before_reporting_filter = len(filtered)
        filtered = filter_by_reporting_date(
            filtered,
            reporting_from_date,
            reporting_to_date,
        )
        reporting_excluded = before_reporting_filter - len(filtered)

        filtered = prepare_for_editor(filtered)
        filtered = sort_report(filtered)

        st.session_state.merged_df = merged
        st.session_state.filtered_df = filtered

        st.success(
            f"Merge completed. **{len(merged)} unique records** found. "
            f"**{duplicates_removed} exact duplicate(s)** removed. "
            f"**{len(filtered)} record(s)** match both the activity-period and reporting-date filters. "
            f"**{reporting_excluded} record(s)** were excluded by reporting date."
        )


# ============================================================
# 5. REVIEW / EDIT
# ============================================================
st.markdown(
    '<div class="section-title">5. Review & Edit Report</div>',
    unsafe_allow_html=True,
)

if st.session_state.filtered_df.empty:
    st.info(
        "No filtered records yet. Upload your data, select the report period, "
        "and click **Merge Excel + WhatsApp Data**."
    )
else:
    editor_df = prepare_for_editor(
        st.session_state.filtered_df
    )

    # IMPORTANT:
    # Start Date / End Date are DateColumn because their underlying
    # pandas dtype is datetime64. TextColumn would cause the
    # StreamlitAPIException shown previously.
    edited_df = st.data_editor(
        editor_df,
        column_config={
            "S.No": st.column_config.NumberColumn(
                "S.No",
                disabled=True,
                width="small",
            ),
            "Reporting Date": st.column_config.DateColumn(
                "Reporting Date",
                format="DD/MM/YYYY",
                width="medium",
            ),
            "Ticket No": st.column_config.TextColumn(
                "Ticket No",
                width="medium",
            ),
            "Start Date": st.column_config.DateColumn(
                "Start Date",
                format="DD/MM/YYYY",
                width="medium",
            ),
            "End Date": st.column_config.DateColumn(
                "End Date",
                format="DD/MM/YYYY",
                width="medium",
            ),
            "Project Site": st.column_config.TextColumn(
                "Project Site",
                width="medium",
            ),
            "Activities": st.column_config.TextColumn(
                "Activities",
                width="large",
            ),
            "KE Representative": st.column_config.TextColumn(
                "KE Representative",
                width="medium",
            ),
            "Vendor Supervisor": st.column_config.TextColumn(
                "Vendor Supervisor",
                width="medium",
            ),
            "Manpower (Labour)": st.column_config.NumberColumn(
                "Manpower (Labour)",
                min_value=0,
                step=1,
                width="medium",
            ),
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="report_editor",
    )

    # Keep the edited result in session state.
    edited_df = edited_df.copy()

    for col in DATE_COLUMNS:
        edited_df[col] = normalize_datetime_series(edited_df[col])

    edited_df["Manpower (Labour)"] = pd.to_numeric(
        edited_df["Manpower (Labour)"],
        errors="coerce",
    ).astype("Float64")

    for col in TEXT_COLUMNS:
        edited_df[col] = edited_df[col].apply(clean_text)

    edited_df = sort_report(edited_df)

    st.session_state.filtered_df = edited_df


# ============================================================
# 6. VALIDATION / SUMMARY
# ============================================================
if not st.session_state.filtered_df.empty:
    current_df = prepare_for_editor(
        st.session_state.filtered_df
    )

    validation = validate_dataframe(current_df)

    total = len(current_df)
    complete = int((validation == "Complete").sum())
    incomplete = int((validation == "Incomplete").sum())

    manpower_total = pd.to_numeric(
        current_df["Manpower (Labour)"],
        errors="coerce",
    ).fillna(0).sum()

    st.markdown(
        '<div class="section-title">6. Report Summary</div>',
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.metric("Total Records", total)

    with m2:
        st.metric("Complete", complete)

    with m3:
        st.metric("Incomplete", incomplete)

    with m4:
        st.metric(
            "Total Manpower",
            int(manpower_total)
            if float(manpower_total).is_integer()
            else round(float(manpower_total), 2),
        )

    if incomplete > 0:
        st.warning(
            f"⚠️ {incomplete} record(s) have missing required fields. "
            "Review the editable table above before downloading."
        )

        with st.expander("Show incomplete records"):
            incomplete_df = current_df[
                validation == "Incomplete"
            ].copy()

            st.dataframe(
                incomplete_df,
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.success(
            "✅ All displayed records contain the required fields."
        )


# ============================================================
# 7. DOWNLOAD
# ============================================================
if not st.session_state.filtered_df.empty:
    st.markdown(
        '<div class="section-title">7. Download Consolidated Report</div>',
        unsafe_allow_html=True,
    )

    final_df = prepare_for_editor(
        st.session_state.filtered_df
    )
    final_df = sort_report(final_df)

    # Remove completely blank ticket rows before export.
    final_df["Ticket No"] = final_df["Ticket No"].apply(clean_text)
    final_df = final_df[
        final_df["Ticket No"] != ""
    ].copy()
    final_df = sort_report(final_df)

    excel_output = create_excel_report(
        final_df,
        from_date,
        to_date,
        reporting_from_date,
        reporting_to_date,
    )

    filename = (
        "Merged_Daily_Report_"
        f"{safe_filename_date(from_date)}_to_"
        f"{safe_filename_date(to_date)}.xlsx"
    )

    st.download_button(
        label="📥 Download Consolidated Excel",
        data=excel_output.getvalue(),
        file_name=filename,
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        type="primary",
        use_container_width=True,
    )


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.header("Instructions")

    st.markdown(
        """
        **Workflow**

        1. Select the **Activity From/To Date** and **Reporting Date From/To** filters.
        2. Upload the existing Excel report.
        3. Upload WhatsApp TXT and/or paste WhatsApp messages.
        4. Click **Parse Pasted Messages** if you pasted text.
        5. Click **Merge Excel + WhatsApp Data**.
        6. Review/edit the records.
        7. Correct any incomplete records.
        8. Download the consolidated Excel.

        **Date filtering**

        The app applies two filters:

        1. **Activity Period** — records are included when their activity interval overlaps the selected period.
        2. **Reporting Date** — records are included when the WhatsApp message/report date falls within the selected reporting-date range.

        For example:

        - Activity: 05-Sep → 12-Sep
        - Selected: 10-Sep → 15-Sep
        - Result: **Included**

        **Duplicate handling**

        The app does **not** remove duplicates using Ticket No alone.

        An exact duplicate is identified using:

        - Ticket No
        - Start Date
        - End Date
        - Project Site
        - Activities
        - KE Representative
        - Vendor Supervisor
        - Manpower

        This allows the same ticket value to legitimately appear for
        different sites/dates.

        **Important**

        Do not upload operational Excel/WhatsApp data to GitHub.
        Keep the GitHub repository private.
        """
    )

    if st.button(
        "Clear Current Data",
        use_container_width=True,
    ):
        st.session_state.excel_df = pd.DataFrame(
            columns=TARGET_COLUMNS
        )
        st.session_state.whatsapp_txt_df = pd.DataFrame(
            columns=TARGET_COLUMNS
        )
        st.session_state.whatsapp_pasted_df = pd.DataFrame(
            columns=TARGET_COLUMNS
        )
        st.session_state.whatsapp_df = pd.DataFrame(
            columns=TARGET_COLUMNS
        )
        st.session_state.merged_df = pd.DataFrame(
            columns=TARGET_COLUMNS
        )
        st.session_state.filtered_df = pd.DataFrame(
            columns=TARGET_COLUMNS
        )
        st.session_state.last_excel_name = ""
        st.session_state.last_txt_name = ""
        st.rerun()
