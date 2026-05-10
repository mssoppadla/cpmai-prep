"""Bulk-upload questions from an admin-supplied Excel sheet.

Two responsibilities:

  1. `build_template()` — emit a downloadable .xlsx with column headers,
     example rows, and data-validation dropdowns for the enum-shaped
     columns (difficulty, question_type) so admins can't typo them.

  2. `parse_workbook(stream)` — read an uploaded sheet, map each row
     to a `QuestionAdminIn` payload, and return both the valid payloads
     and per-row errors. Caller (the endpoint) decides whether to
     commit the valid ones and report the errors back.

Format (wide, one row per question):

    A: stem                       (required)
    B: topic_code                 (required, case-insensitive: BU/DU/DP/MD/EV/DE)
    C: difficulty                 (required: easy / medium / hard)
    D: question_type              (default single_choice; multi_choice allowed)
    E: domain                     (optional)
    F: task                       (optional)
    G: enablers                   (optional, comma-separated → list[str])
    H: remarks                    (optional, admin-only note)
    I: explanation                (optional, shown to learner after submit)
    J: is_active                  (default true; accepts y/n, true/false, 1/0)
    K: option_a_text              (required)
    L: option_a_is_correct        (required: true/false)
    M: option_a_reasoning         (optional)
    N..M: option_b_*              (required — at least 2 options needed)
    P..R: option_c_*              (optional)
    S..U: option_d_*
    V..X: option_e_*
    Y..AA: option_f_*

Wide format chosen over long because admins maintaining a question
bank in Excel work one-question-at-a-time and benefit from seeing the
full row at once. Long format would compact variable-option counts but
is hideous to edit.

Hard caps (enforced at the endpoint, not here):
    file size  ≤ 5 MB
    row count  ≤ 500 questions per upload
"""
from io import BytesIO
from dataclasses import dataclass

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.comments import Comment
from pydantic import ValidationError as PydanticValidationError

from app.schemas.question import QuestionAdminIn, QuestionOptionIn


# Column layout — must match the docstring above. Single source of truth
# for both the template writer and the parser.
COLUMNS: list[tuple[str, str]] = [
    ("stem",           "Question stem (required)"),
    ("topic_code",     "CPMAI phase code: BU, DU, DP, MD, EV, or DE (required)"),
    ("difficulty",     "easy / medium / hard (required)"),
    ("question_type",  "single_choice (default) or multi_choice"),
    ("domain",         "Optional sub-area string"),
    ("task",           "Optional task description"),
    ("enablers",       "Optional comma-separated list of enablers"),
    ("remarks",        "Optional admin-only note (not shown to learner)"),
    ("explanation",    "Optional general explanation, shown after submit"),
    ("is_active",      "true (default) / false / 1 / 0 / y / n"),
]
OPTION_LETTERS = ("A", "B", "C", "D", "E", "F")
for L in OPTION_LETTERS:
    COLUMNS += [
        (f"option_{L.lower()}_text",      f"Option {L} text"
            + (" (required)" if L in ("A", "B") else " (leave blank if unused)")),
        (f"option_{L.lower()}_is_correct", f"Option {L} correctness: true/false"),
        (f"option_{L.lower()}_reasoning",  f"Option {L} reasoning (correct → why; "
                                            f"wrong → why wrong)"),
    ]
HEADERS = [c[0] for c in COLUMNS]
HEADER_NOTES = {c[0]: c[1] for c in COLUMNS}


# --------------------------------------------------------- bool parsing
_TRUTHY = {"true", "t", "yes", "y", "1"}
_FALSY  = {"false", "f", "no",  "n", "0"}


def _parse_bool(v, default: bool | None = None) -> bool:
    """Forgiving bool parser — Excel cells come through as int / str / bool."""
    if v is None or (isinstance(v, str) and not v.strip()):
        if default is None:
            raise ValueError("expected a yes/no value, got blank")
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in _TRUTHY: return True
    if s in _FALSY:  return False
    raise ValueError(f"could not interpret {v!r} as yes/no")


def _cell_str(v) -> str:
    """Cell → trimmed string. Empty cells become ''."""
    if v is None:
        return ""
    return str(v).strip()


# =========================================================== template
def build_template() -> bytes:
    """Generate the .xlsx admins download. Includes:
       - frozen header row with column titles + a docstring-comment
         on each header explaining the field
       - 3 example rows: a single-choice, a multi-choice, and a
         minimal-fields example
       - data-validation dropdowns on `difficulty`, `question_type`,
         and every `option_*_is_correct` so a wrong value can't be saved
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Questions"

    header_fill = PatternFill("solid", fgColor="E5E7EB")
    header_font = Font(bold=True)

    # Header row.
    for i, name in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=i, value=name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.comment = Comment(HEADER_NOTES[name], "CPMAI Bulk Upload")

    ws.freeze_panes = "A2"
    # Column widths — guesstimated for readability; admins can resize.
    for i, name in enumerate(HEADERS, start=1):
        if name == "stem" or name == "explanation":
            ws.column_dimensions[get_column_letter(i)].width = 60
        elif name.endswith("_text") or name.endswith("_reasoning"):
            ws.column_dimensions[get_column_letter(i)].width = 35
        else:
            ws.column_dimensions[get_column_letter(i)].width = 16

    # Data-validation dropdowns. Apply to a generous range so admins
    # don't have to extend the validation when adding rows.

    def col(name: str) -> str:
        return get_column_letter(HEADERS.index(name) + 1)

    def col_range(name: str, start_row: int = 2, end_row: int = 1000) -> str:
        """Build a single-column range like 'C2:C1000' — openpyxl
        requires the column letter on BOTH sides; 'C2:1000' raises
        ValueError on workbook save."""
        c = col(name)
        return f"{c}{start_row}:{c}{end_row}"

    diff_dv = DataValidation(type="list", formula1='"easy,medium,hard"',
                              allow_blank=False)
    diff_dv.error = "Use easy / medium / hard"
    diff_dv.errorTitle = "Invalid difficulty"
    ws.add_data_validation(diff_dv)
    diff_dv.add(col_range('difficulty'))

    qtype_dv = DataValidation(type="list",
                               formula1='"single_choice,multi_choice"',
                               allow_blank=True)
    qtype_dv.error = "Use single_choice or multi_choice"
    qtype_dv.errorTitle = "Invalid question_type"
    ws.add_data_validation(qtype_dv)
    qtype_dv.add(col_range('question_type'))

    bool_dv = DataValidation(type="list", formula1='"true,false"',
                              allow_blank=True)
    bool_dv.error = "Use true / false"
    bool_dv.errorTitle = "Invalid boolean"
    ws.add_data_validation(bool_dv)
    bool_dv.add(col_range('is_active'))
    for L in OPTION_LETTERS:
        bool_dv.add(col_range(f'option_{L.lower()}_is_correct'))

    topic_dv = DataValidation(type="list",
                               formula1='"BU,DU,DP,MD,EV,DE"',
                               allow_blank=False)
    topic_dv.error = "Use one of: BU, DU, DP, MD, EV, DE"
    topic_dv.errorTitle = "Invalid topic_code"
    ws.add_data_validation(topic_dv)
    topic_dv.add(col_range('topic_code'))

    # Three example rows — pre-filled so admins can copy-and-modify.
    examples: list[dict] = [
        {
            "stem": "Which CPMAI phase is dedicated to assessing data quality?",
            "topic_code": "DU", "difficulty": "easy",
            "question_type": "single_choice",
            "domain": "Data Understanding > Quality",
            "explanation": "Phase 2 (Data Understanding) is where data is profiled.",
            "is_active": "true",
            "option_a_text": "Phase 1 — Business Understanding", "option_a_is_correct": "false",
            "option_a_reasoning": "Phase 1 defines the business goal, not data quality.",
            "option_b_text": "Phase 2 — Data Understanding", "option_b_is_correct": "true",
            "option_b_reasoning": "Correct — Phase 2 is dedicated to data assessment.",
            "option_c_text": "Phase 4 — Modeling", "option_c_is_correct": "false",
            "option_c_reasoning": "Modeling consumes prepared data; quality is assessed earlier.",
            "option_d_text": "Phase 6 — Operationalization", "option_d_is_correct": "false",
            "option_d_reasoning": "Operationalization is for deployed models, not raw data.",
        },
        {
            "stem": "Which phases involve hands-on work with data? (pick all that apply)",
            "topic_code": "DP", "difficulty": "medium",
            "question_type": "multi_choice",
            "is_active": "true",
            "option_a_text": "Data Understanding", "option_a_is_correct": "true",
            "option_a_reasoning": "Data profiling and quality assessment happen here.",
            "option_b_text": "Data Preparation", "option_b_is_correct": "true",
            "option_b_reasoning": "Cleansing, transformation, and feature engineering.",
            "option_c_text": "Modeling", "option_c_is_correct": "false",
            "option_c_reasoning": "Modeling consumes data but doesn't manipulate it directly.",
            "option_d_text": "Business Understanding", "option_d_is_correct": "false",
            "option_d_reasoning": "Business Understanding is goal-setting, not data work.",
        },
        {
            "stem": "Minimal example: what does CPMAI stand for?",
            "topic_code": "BU", "difficulty": "easy",
            "option_a_text": "Cognitive Project Management for AI", "option_a_is_correct": "true",
            "option_b_text": "Continuous Process Modeling and Iteration", "option_b_is_correct": "false",
        },
    ]
    for rownum, ex in enumerate(examples, start=2):
        for i, name in enumerate(HEADERS, start=1):
            if name in ex:
                ws.cell(row=rownum, column=i, value=ex[name])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============================================================ parser
@dataclass
class ParseResult:
    """Outcome of parsing the upload. The endpoint commits `valid`
    entries and reports `errors` to the admin so they can fix the
    failing rows in their sheet and re-upload only those."""
    valid: list[tuple[int, QuestionAdminIn, str]]   # (row_num, payload, topic_code)
    errors: list[dict]                               # {row, field, message}


def _build_payload(row: dict, row_num: int) -> tuple[QuestionAdminIn, str]:
    """Validate + coerce a single row into a QuestionAdminIn.
    Returns (payload, topic_code) — the endpoint resolves topic_code
    to topic_id outside this module so we don't need a DB session here.
    Raises ValueError with a human-readable message on any problem."""
    stem = _cell_str(row.get("stem"))
    if not stem:
        raise ValueError("stem is required")

    topic_code = _cell_str(row.get("topic_code")).upper()
    if not topic_code:
        raise ValueError("topic_code is required")

    difficulty = _cell_str(row.get("difficulty")).lower()
    if difficulty not in {"easy", "medium", "hard"}:
        raise ValueError(f"difficulty must be easy/medium/hard, got {difficulty!r}")

    qt = _cell_str(row.get("question_type")).lower() or "single_choice"
    if qt not in {"single_choice", "multi_choice"}:
        raise ValueError(f"question_type must be single_choice or multi_choice, got {qt!r}")

    enablers_raw = _cell_str(row.get("enablers"))
    enablers = [e.strip() for e in enablers_raw.split(",") if e.strip()] \
                if enablers_raw else []

    is_active = _parse_bool(row.get("is_active"), default=True)

    options: list[QuestionOptionIn] = []
    for L in OPTION_LETTERS:
        text = _cell_str(row.get(f"option_{L.lower()}_text"))
        if not text:
            continue   # blank option columns are skipped
        try:
            is_correct = _parse_bool(row.get(f"option_{L.lower()}_is_correct"),
                                      default=False)
        except ValueError as e:
            raise ValueError(f"option_{L.lower()}_is_correct: {e}")
        reasoning = _cell_str(row.get(f"option_{L.lower()}_reasoning")) or None
        options.append(QuestionOptionIn(
            option_letter=L, text=text,
            is_correct=is_correct, reasoning=reasoning,
        ))

    if len(options) < 2:
        raise ValueError("at least 2 options required (option_a_text + option_b_text)")

    # topic_id is set later by the caller after looking up topic_code.
    # Use 0 as a placeholder — Pydantic validates type only.
    try:
        payload = QuestionAdminIn(
            stem=stem, topic_id=0,
            domain=(_cell_str(row.get("domain")) or None),
            task=(_cell_str(row.get("task")) or None),
            enablers=enablers,
            remarks=(_cell_str(row.get("remarks")) or None),
            difficulty=difficulty,                 # type: ignore[arg-type]
            question_type=qt,                      # type: ignore[arg-type]
            explanation=(_cell_str(row.get("explanation")) or None),
            options=options,
            is_active=is_active,
        )
    except PydanticValidationError as e:
        raise ValueError(f"schema validation: {e.errors()[0]['msg']}")
    return payload, topic_code


def parse_workbook(stream: bytes, *, max_rows: int = 500) -> ParseResult:
    """Read a .xlsx upload and return per-row payloads + errors.

    `max_rows` is enforced ABOVE the schema: a 1000-row sheet returns
    an immediate "too many" error before any row is parsed, so we
    don't waste compute on a sheet we'll reject anyway.
    """
    try:
        wb = load_workbook(BytesIO(stream), data_only=True, read_only=True)
    except Exception as e:
        return ParseResult(valid=[], errors=[{
            "row": 0, "field": "file",
            "message": f"could not open as .xlsx: {e}"}])

    ws = wb.active

    # First row = headers. Read them and verify.
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return ParseResult(valid=[], errors=[{
            "row": 0, "field": "file", "message": "sheet is empty"}])

    headers_in_file = [_cell_str(h) for h in header_row]
    missing = [h for h in HEADERS if h not in headers_in_file]
    if missing:
        return ParseResult(valid=[], errors=[{
            "row": 1, "field": "headers",
            "message": (f"missing required header columns: {missing}. "
                         f"Download the latest template via the "
                         f"'Download template' button.")}])

    # Build positional → name index for fast row lookup.
    name_at = {i: name for i, name in enumerate(headers_in_file)}

    valid: list[tuple[int, QuestionAdminIn, str]] = []
    errors: list[dict] = []
    seen_data_rows = 0

    for row_num, row_values in enumerate(rows_iter, start=2):
        # Skip fully-blank rows (admins often leave trailing empties).
        if all(v is None or (isinstance(v, str) and not v.strip())
                for v in row_values):
            continue
        seen_data_rows += 1
        if seen_data_rows > max_rows:
            errors.append({
                "row": row_num, "field": "file",
                "message": (f"too many rows: capped at {max_rows} per upload. "
                             f"Split into smaller files."),
            })
            break
        row = {name_at.get(i): v for i, v in enumerate(row_values)}
        try:
            payload, topic_code = _build_payload(row, row_num)
            valid.append((row_num, payload, topic_code))
        except ValueError as e:
            errors.append({
                "row": row_num, "field": "row",
                "message": str(e),
            })

    return ParseResult(valid=valid, errors=errors)
