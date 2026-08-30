import os
import re
import sys

import cv2
import fitz
import pytesseract
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QLabel,
    QPushButton,
    QFrame,
    QTextEdit,
    QHBoxLayout,
    QVBoxLayout,
    QButtonGroup,
)


# ============================================================
# TESSERACT
# ============================================================

pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"
os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin"


# ============================================================
# COLORS
# ============================================================

BG = "#FFF7ED"
CARD = "#FFFFFF"

BLUE = "#4F46E5"
BLUE_HOVER = "#4338CA"

PURPLE = "#8B5CF6"
PURPLE_HOVER = "#7C3AED"

PINK = "#EC4899"
PINK_HOVER = "#DB2777"

GREEN = "#22C55E"
GREEN_DARK = "#16A34A"

ORANGE = "#F97316"
YELLOW = "#FACC15"

DARK = "#312E81"
TEXT = "#374151"
MUTED = "#6B7280"

BORDER = "#E5E7EB"

DANGER = "#EF4444"


# ============================================================
# GLOBAL DATA
# ============================================================

raw_ocr_text = ""
document_data = {}
document_type = "PASSPORT"


# ============================================================
# MRZ FUNCTIONS
# ============================================================

def normalize_mrz_line(line):
    line = line.upper().strip()

    replacements = {
        "«": "<",
        "‹": "<",
        "≤": "<",
        "﹤": "<",
        "＜": "<",
        "—": "<",
        "–": "<",
        "_": "<",
        "|": "<",
        " ": ""
    }

    for old, new in replacements.items():
        line = line.replace(old, new)

    return re.sub(r"[^A-Z0-9<]", "", line)


def mrz_score(line1, line2):

    if not line1 or not line2:
        return -100

    score = 0

    if line1.startswith("P<"):
        score += 40

    elif line1.startswith("P"):
        score += 20

    if 38 <= len(line1) <= 50:
        score += 15

    if 38 <= len(line2) <= 50:
        score += 15

    if "<<" in line1:
        score += 30

    if re.search(r"\d{6}", line2):
        score += 20

    return score


def find_mrz(text):

    candidates = []

    for line in text.upper().splitlines():

        line = normalize_mrz_line(line)

        if len(line) >= 30:
            candidates.append(line)

    best_pair = None
    best_score = -100

    for i, line1 in enumerate(candidates):

        for j in range(
            i + 1,
            min(i + 4, len(candidates))
        ):

            line2 = candidates[j]

            score = mrz_score(
                line1,
                line2
            )

            if score > best_score:

                best_score = score
                best_pair = line1, line2

    if best_pair is None:
        return None, None

    return (
        best_pair[0][:44],
        best_pair[1][:44]
    )


def clean_name(value):

    value = value.upper()
    value = value.replace("<", " ")

    value = re.sub(
        r"[^A-Z ]",
        "",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip().title()


def extract_name_from_mrz(line1):

    if not line1:
        return "Not detected", "Not detected"

    line1 = normalize_mrz_line(line1)

    if line1.startswith("P<"):
        name_area = line1[5:]

    elif line1.startswith("P"):
        name_area = line1[2:]

    else:
        name_area = line1

    separator = name_area.find("<<")

    if separator == -1:
        return (
            clean_name(name_area),
            "Not detected"
        )

    surname_raw = name_area[:separator]
    given_raw = name_area[separator + 2:]

    surname = clean_name(
        surname_raw.rstrip("<")
    )

    given_names = clean_name(
        given_raw.rstrip("<")
    )

    return (
        surname or "Not detected",
        given_names or "Not detected"
    )


def normalize_date_digits(value):

    value = value.upper()

    replacements = {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "Z": "2",
        "S": "5",
        "G": "6",
        "T": "7",
        "B": "8"
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    return re.sub(
        r"[^0-9]",
        "",
        value
    )


def format_mrz_date(value, date_type):

    value = normalize_date_digits(value)

    if len(value) != 6:
        return "Not detected"

    try:

        year = int(value[:2])
        month = int(value[2:4])
        day = int(value[4:6])

        if not 1 <= month <= 12:
            return "Not detected"

        if not 1 <= day <= 31:
            return "Not detected"

        if date_type == "birth":

            full_year = (
                2000 + year
                if year <= 26
                else 1900 + year
            )

        else:

            full_year = 2000 + year

        return (
            f"{day:02d}/"
            f"{month:02d}/"
            f"{full_year}"
        )

    except ValueError:

        return "Not detected"


def parse_mrz(line1, line2):

    if not line1 or not line2:
        return None

    line1 = normalize_mrz_line(
        line1
    ).ljust(44, "<")

    line2 = normalize_mrz_line(
        line2
    ).ljust(44, "<")

    if not line1.startswith("P"):
        return None

    data = {
        "Document Type": "PASSPORT"
    }

    issuing_country = (
        line1[2:5]
        .replace("<", "")
    )

    data["Issuing Country"] = (
        issuing_country
        if issuing_country
        else "Not detected"
    )

    surname, given_names = (
        extract_name_from_mrz(line1)
    )

    data["Surname"] = surname
    data["Given Names"] = given_names

    passport_number = (
        line2[0:9]
        .replace("<", "")
    )

    data["Passport Number"] = (
        passport_number
        if passport_number
        else "Not detected"
    )

    nationality = (
        line2[10:13]
        .replace("<", "")
    )

    data["Nationality"] = (
        nationality
        if nationality
        else "Not detected"
    )

    data["Date of Birth"] = format_mrz_date(
        line2[13:19],
        "birth"
    )

    sex = line2[20:21]

    data["Sex"] = (
        "UNSPECIFIED"
        if sex == "<"
        else sex
    )

    data["Date of Expiry"] = format_mrz_date(
        line2[21:27],
        "expiry"
    )

    data["MRZ"] = (
        line1[:44]
        + "\n"
        + line2[:44]
    )

    return data


# ============================================================
# PASSPORT OCR
# ============================================================

def run_mrz_ocr(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        None,
        fx=2,
        fy=2,
        interpolation=cv2.INTER_CUBIC
    )

    height = gray.shape[0]

    crop = gray[
        int(height * 0.38):,
        :
    ]

    results = []

    variants = [

        cv2.threshold(
            crop,
            0,
            255,
            cv2.THRESH_BINARY
            + cv2.THRESH_OTSU
        )[1],

        cv2.adaptiveThreshold(
            crop,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11
        ),

        crop
    ]

    config = (
        "--oem 3 "
        "--psm 6 "
        "-c "
        "tessedit_char_whitelist="
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789<"
    )

    for processed in variants:

        result = pytesseract.image_to_string(
            processed,
            config=config
        )

        line1, line2 = find_mrz(
            result
        )

        if line1 and line2:

            results.append(
                (
                    mrz_score(
                        line1,
                        line2
                    ),
                    line1,
                    line2,
                    result
                )
            )

    if not results:
        return "", None, None

    results.sort(
        key=lambda x: x[0],
        reverse=True
    )

    best = results[0]

    return (
        best[3],
        best[1],
        best[2]
    )


def run_general_ocr(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        None,
        fx=1.6,
        fy=1.6,
        interpolation=cv2.INTER_CUBIC
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    enhanced = clahe.apply(gray)

    return pytesseract.image_to_string(
        enhanced,
        config="--oem 3 --psm 6"
    )


def passport_document_score(
    text,
    line1=None,
    line2=None
):

    upper = text.upper()

    score = 0

    if line1 and line2:

        mrz_value = mrz_score(
            line1,
            line2
        )

        if mrz_value >= 80:
            score += 10

        elif mrz_value >= 60:
            score += 7

        elif mrz_value >= 40:
            score += 4

    passport_words = [

        "PASSPORT",
        "REPUBLIC",
        "NATIONALITY",
        "DATE OF BIRTH",
        "DATE OF EXPIRY",
        "PLACE OF BIRTH",
        "AUTHORITY",
        "SURNAME",
        "GIVEN NAMES"
    ]

    for word in passport_words:

        if word in upper:
            score += 2

    if "P<" in upper:
        score += 8

    if re.search(
        r"P[A-Z<]{2,4}[A-Z<]{20,}",
        upper
    ):
        score += 6

    mrz_lines = []

    for line in upper.splitlines():

        normalized = normalize_mrz_line(
            line
        )

        if len(normalized) >= 30:
            mrz_lines.append(
                normalized
            )

    if len(mrz_lines) >= 2:
        score += 5

    return score


def process_passport(image):

    mrz_text, line1, line2 = (
        run_mrz_ocr(image)
    )

    full_text = run_general_ocr(
        image
    )

    combined = (
        full_text
        + "\n"
        + mrz_text
    )

    data = {}

    if line1 and line2:

        parsed = parse_mrz(
            line1,
            line2
        )

        if parsed:
            data = parsed

    passport_score = (
        passport_document_score(
            combined,
            line1,
            line2
        )
    )

    if not data:

        data = {
            "Document Type": "PASSPORT"
        }

    data["_score"] = passport_score

    return combined, data


# ============================================================
# AADHAAR FUNCTIONS
# ============================================================

def normalize_aadhaar_ocr(text):

    replacements = {

        "AADHAAR": "AADHAAR",
        "ADHAAR": "AADHAAR",
        "A4DHAAR": "AADHAAR",
        "A4HAAR": "AADHAAR",

        "UNIQUE IDENTIFICATION":
            "UNIQUE IDENTIFICATION",

        "DOB.": "DOB",
        "D0B": "DOB",
        "D08": "DOB",

        "FEMA1E": "FEMALE",
        "FEMAIE": "FEMALE",
        "MA1E": "MALE"
    }

    result = text.upper()

    for old, new in replacements.items():
        result = result.replace(
            old,
            new
        )

    return result


def extract_aadhaar_number(text):

    text = normalize_aadhaar_ocr(
        text
    )

    spaced_patterns = [

        r"(?<!\d)"
        r"(\d{4})[\s\-]*"
        r"(\d{4})[\s\-]*"
        r"(\d{4})"
        r"(?!\d)",

        r"(?<!\d)"
        r"(\d{4})\s+"
        r"(\d{4})\s+"
        r"(\d{4})"
        r"(?!\d)"
    ]

    candidates = []

    for pattern in spaced_patterns:

        matches = re.findall(
            pattern,
            text
        )

        for match in matches:

            number = "".join(match)

            if len(number) == 12:

                candidates.append(
                    number
                )

    if candidates:

        for number in candidates:

            if number[0] not in (
                "0",
                "1"
            ):

                return (
                    number[:4]
                    + " "
                    + number[4:8]
                    + " "
                    + number[8:]
                )

        number = candidates[0]

        return (
            number[:4]
            + " "
            + number[4:8]
            + " "
            + number[8:]
        )

    digits = re.sub(
        r"\D",
        "",
        text
    )

    possible = re.findall(
        r"(?<!\d)\d{12}(?!\d)",
        digits
    )

    if possible:

        number = possible[0]

        return (
            number[:4]
            + " "
            + number[4:8]
            + " "
            + number[8:]
        )

    return "Not detected"


def extract_aadhaar_name(text):

    lines = [

        re.sub(
            r"\s+",
            " ",
            line.strip()
        )

        for line in text.splitlines()

        if line.strip()
    ]

    blocked = [

        "AADHAAR",
        "GOVERNMENT",
        "INDIA",
        "UNIQUE",
        "IDENTIFICATION",
        "AUTHORITY",
        "UIDAI",
        "DOB",
        "DATE OF BIRTH",
        "MALE",
        "FEMALE",
        "ADDRESS",
        "VID",
        "YEAR",
        "ENROLMENT",
        "ENROLLMENT",
        "DOWNLOAD",
        "IDENTIFICATION AUTHORITY"
    ]

    date_pattern = re.compile(
        r"\b\d{1,4}"
        r"[\/\-.]"
        r"\d{1,2}"
        r"[\/\-.]"
        r"\d{2,4}\b"
    )

    number_pattern = re.compile(
        r"\d{4}\s*\d{4}\s*\d{4}"
    )

    candidates = []

    for index, line in enumerate(lines):

        upper = line.upper()

        if number_pattern.search(line):
            continue

        if date_pattern.search(line):
            continue

        if any(
            word in upper
            for word in blocked
        ):
            continue

        cleaned = re.sub(
            r"[^A-Za-z ]",
            "",
            line
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned
        ).strip()

        words = cleaned.split()

        if not 2 <= len(words) <= 6:
            continue

        if not 3 <= len(cleaned) <= 60:
            continue

        if not all(

            len(
                re.sub(
                    r"[^A-Za-z]",
                    "",
                    word
                )
            ) >= 2

            for word in words
        ):
            continue

        score = 0

        if index <= 5:
            score += 3

        if len(words) in (
            2,
            3,
            4
        ):
            score += 3

        if all(
            word[0].isalpha()
            for word in words
        ):
            score += 2

        candidates.append(
            (
                score,
                cleaned.title()
            )
        )

    if candidates:

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        return candidates[0][1]

    return "Not detected"


def extract_date(text):

    patterns = [

        r"\b(\d{2})"
        r"[\/\-.]"
        r"(\d{2})"
        r"[\/\-.]"
        r"(\d{4})\b",

        r"\b(\d{2})"
        r"[\/\-.]"
        r"(\d{2})"
        r"[\/\-.]"
        r"(\d{2})\b",

        r"\b(\d{4})"
        r"[\/\-.]"
        r"(\d{2})"
        r"[\/\-.]"
        r"(\d{2})\b"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if not match:
            continue

        groups = match.groups()

        try:

            if len(groups[0]) == 4:

                year = int(groups[0])
                month = int(groups[1])
                day = int(groups[2])

            else:

                day = int(groups[0])
                month = int(groups[1])
                year = int(groups[2])

                if year < 100:

                    year += (
                        2000
                        if year <= 26
                        else 1900
                    )

            if (
                1 <= day <= 31
                and
                1 <= month <= 12
            ):

                return (
                    f"{day:02d}/"
                    f"{month:02d}/"
                    f"{year}"
                )

        except ValueError:

            continue

    return "Not detected"


def extract_aadhaar_dob(text):

    normalized = normalize_aadhaar_ocr(
        text
    )

    lines = [

        line.strip()

        for line in normalized.splitlines()

        if line.strip()
    ]

    date_patterns = [

        r"\b\d{2}"
        r"[\/\-.]"
        r"\d{2}"
        r"[\/\-.]"
        r"\d{4}\b",

        r"\b\d{2}"
        r"[\/\-.]"
        r"\d{2}"
        r"[\/\-.]"
        r"\d{2}\b",

        r"\b\d{4}"
        r"[\/\-.]"
        r"\d{2}"
        r"[\/\-.]"
        r"\d{2}\b"
    ]

    for index, line in enumerate(lines):

        context = line

        if index > 0:
            context += " " + lines[index - 1]

        if index + 1 < len(lines):
            context += " " + lines[index + 1]

        upper = context.upper()

        if not (
            "DOB" in upper
            or
            "DATE OF BIRTH" in upper
            or
            "BIRTH" in upper
        ):
            continue

        for pattern in date_patterns:

            match = re.search(
                pattern,
                context
            )

            if match:

                date = extract_date(
                    match.group()
                )

                if date != "Not detected":
                    return date

        year_match = re.search(
            r"\b(19\d{2}|20\d{2})\b",
            context
        )

        if year_match:
            return year_match.group()

    return "Not detected"


def extract_aadhaar_gender(text):

    upper = normalize_aadhaar_ocr(
        text
    )

    if re.search(
        r"\bFEMALE\b",
        upper
    ):
        return "Female"

    if re.search(
        r"\bMALE\b",
        upper
    ):
        return "Male"

    return "Not detected"


def aadhaar_document_score(text):

    upper = normalize_aadhaar_ocr(
        text
    )

    score = 0

    if "AADHAAR" in upper:
        score += 5

    if "UNIQUE IDENTIFICATION" in upper:
        score += 3

    if "GOVERNMENT OF INDIA" in upper:
        score += 3

    if "UIDAI" in upper:
        score += 3

    if re.search(
        r"\b\d{4}\s+\d{4}\s+\d{4}\b",
        upper
    ):
        score += 5

    digits = re.sub(
        r"\D",
        "",
        upper
    )

    if re.search(
        r"\d{12}",
        digits
    ):
        score += 4

    if "DOB" in upper:
        score += 2

    if "DATE OF BIRTH" in upper:
        score += 2

    if (
        "MALE" in upper
        or
        "FEMALE" in upper
    ):
        score += 2

    return score


def process_aadhaar(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        None,
        fx=1.7,
        fy=1.7,
        interpolation=cv2.INTER_CUBIC
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    enhanced = clahe.apply(
        gray
    )

    otsu = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY
        + cv2.THRESH_OTSU
    )[1]

    adaptive = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11
    )

    variants = [
        enhanced,
        otsu,
        adaptive
    ]

    results = []

    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 11"
    ]

    for processed in variants:

        for config in configs:

            text = pytesseract.image_to_string(
                processed,
                config=config
            )

            if text.strip():
                results.append(text)

    combined = "\n".join(
        results
    )

    best_number = extract_aadhaar_number(
        combined
    )

    best_name = extract_aadhaar_name(
        combined
    )

    best_dob = extract_aadhaar_dob(
        combined
    )

    best_gender = extract_aadhaar_gender(
        combined
    )

    score = aadhaar_document_score(
        combined
    )

    data = {

        "Document Type": "AADHAAR",

        "Aadhaar Number":
            best_number,

        "Name":
            best_name,

        "Date of Birth":
            best_dob,

        "Gender":
            best_gender,

        "_score":
            score
    }

    return combined, data


# ============================================================
# MAIN WINDOW
# ============================================================

class DocumentVerification(QMainWindow):

    def __init__(self):

        super().__init__()

        self.document_type = "PASSPORT"
        self.document_data = {}
        self.raw_ocr_text = ""

        self.setWindowTitle(
            "✨ Document Verification"
        )

        self.setMinimumSize(
            950,
            650
        )

        self.resize(
            1150,
            760
        )

        self.build_ui()


    # ========================================================
    # FONT
    # ========================================================

    def font(
        self,
        size=10,
        bold=False
    ):

        font = QFont()

        font.setPointSize(size)
        font.setBold(bold)

        return font


    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):

        central = QWidget()

        central.setStyleSheet(
            f"""
            QWidget {{
                background-color: {BG};
                color: {TEXT};
            }}
            """
        )

        self.setCentralWidget(
            central
        )

        root_layout = QVBoxLayout(
            central
        )

        root_layout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        root_layout.setSpacing(0)


        # ====================================================
        # HEADER
        # ====================================================

        header = QFrame()

        header.setFixedHeight(
            145
        )

        header.setStyleSheet(
            f"""
            QFrame {{
                background-color: {DARK};
                border-bottom-left-radius: 28px;
                border-bottom-right-radius: 28px;
            }}
            """
        )

        header_layout = QVBoxLayout(
            header
        )

        header_layout.setContentsMargins(
            20,
            18,
            20,
            15
        )

        title = QLabel(
            "✨ Document Verification"
        )

        title.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        title.setFont(
            self.font(
                27,
                True
            )
        )

        title.setStyleSheet(
            """
            color: white;
            border: none;
            """
        )

        header_layout.addWidget(
            title
        )

        subtitle = QLabel(
            "🔎 Extract • Read • Verify"
        )

        subtitle.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        subtitle.setFont(
            self.font(
                12,
                True
            )
        )

        subtitle.setStyleSheet(
            """
            color: #DDD6FE;
            border: none;
            """
        )

        header_layout.addWidget(
            subtitle
        )

        root_layout.addWidget(
            header
        )


        # ====================================================
        # MAIN
        # ====================================================

        main = QWidget()

        main_layout = QVBoxLayout(
            main
        )

        main_layout.setContentsMargins(
            35,
            20,
            35,
            10
        )


        # ====================================================
        # DOCUMENT TYPE
        # ====================================================

        type_title = QLabel(
            "📄  CHOOSE DOCUMENT TYPE"
        )

        type_title.setFont(
            self.font(
                11,
                True
            )
        )

        type_title.setStyleSheet(
            f"""
            color: {DARK};
            border: none;
            """
        )

        main_layout.addWidget(
            type_title
        )

        main_layout.addSpacing(
            10
        )


        # ====================================================
        # DOCUMENT SELECTOR
        # ====================================================

        selector = QHBoxLayout()

        selector.setSpacing(
            15
        )

        self.passport_button = QPushButton(
            "🛂   PASSPORT"
        )

        self.aadhaar_button = QPushButton(
            "🪪   AADHAAR"
        )

        self.passport_button.setCheckable(
            True
        )

        self.aadhaar_button.setCheckable(
            True
        )

        self.passport_button.setChecked(
            True
        )

        # IMPORTANT:
        # Both buttons belong to one exclusive group.
        # This makes them behave like radio buttons
        # while still allowing us to style them nicely.

        self.document_group = QButtonGroup(
            self
        )

        self.document_group.setExclusive(
            True
        )

        self.document_group.addButton(
            self.passport_button
        )

        self.document_group.addButton(
            self.aadhaar_button
        )

        self.passport_button.clicked.connect(
            self.select_passport
        )

        self.aadhaar_button.clicked.connect(
            self.select_aadhaar
        )

        self.passport_button.setMinimumHeight(
            65
        )

        self.aadhaar_button.setMinimumHeight(
            65
        )

        self.passport_button.setFont(
            self.font(
                13,
                True
            )
        )

        self.aadhaar_button.setFont(
            self.font(
                13,
                True
            )
        )

        self.passport_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #EEF2FF;
                color: {BLUE};
                border: 3px solid #C7D2FE;
                border-radius: 18px;
                padding: 10px 25px;
            }}

            QPushButton:hover {{
                background-color: #E0E7FF;
                border: 3px solid #A5B4FC;
            }}

            QPushButton:checked {{
                background-color: {BLUE};
                color: white;
                border: 3px solid {BLUE};
            }}

            QPushButton:pressed {{
                background-color: {BLUE_HOVER};
            }}
            """
        )

        self.aadhaar_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #FFF1F2;
                color: {PINK};
                border: 3px solid #FECDD3;
                border-radius: 18px;
                padding: 10px 25px;
            }}

            QPushButton:hover {{
                background-color: #FFE4E6;
                border: 3px solid #FDA4AF;
            }}

            QPushButton:checked {{
                background-color: {PINK};
                color: white;
                border: 3px solid {PINK};
            }}

            QPushButton:pressed {{
                background-color: {PINK_HOVER};
            }}
            """
        )

        selector.addWidget(
            self.passport_button
        )

        selector.addWidget(
            self.aadhaar_button
        )

        main_layout.addLayout(
            selector
        )

        main_layout.addSpacing(
            15
        )


        # ====================================================
        # CONTROL CARD
        # ====================================================

        control_card = QFrame()

        control_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {CARD};
                border: 2px solid #FED7AA;
                border-radius: 20px;
            }}
            """
        )

        control_layout = QHBoxLayout(
            control_card
        )

        control_layout.setContentsMargins(
            20,
            16,
            20,
            16
        )

        file_section = QVBoxLayout()

        self.document_title = QLabel(
            "🛂  PASSPORT / DOCUMENT"
        )

        self.document_title.setFont(
            self.font(
                10,
                True
            )
        )

        self.document_title.setStyleSheet(
            f"""
            color: {MUTED};
            border: none;
            """
        )

        file_section.addWidget(
            self.document_title
        )

        self.file_label = QLabel(
            "No document selected"
        )

        self.file_label.setFont(
            self.font(
                11
            )
        )

        self.file_label.setStyleSheet(
            f"""
            color: {MUTED};
            border: none;
            """
        )

        file_section.addWidget(
            self.file_label
        )

        control_layout.addLayout(
            file_section,
            1
        )


        # ====================================================
        # BUTTONS
        # ====================================================

        button_section = QHBoxLayout()

        self.select_button = QPushButton(
            "🔍  Select Document"
        )

        self.select_button.setFont(
            self.font(
                11,
                True
            )
        )

        self.select_button.setMinimumHeight(
            45
        )

        self.select_button.clicked.connect(
            self.extract_text
        )

        self.select_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {ORANGE};
                color: white;
                border: none;
                border-radius: 13px;
                padding: 10px 18px;
            }}

            QPushButton:hover {{
                background-color: #EA580C;
            }}

            QPushButton:pressed {{
                background-color: #C2410C;
            }}
            """
        )

        button_section.addWidget(
            self.select_button
        )


        self.save_button = QPushButton(
            "💾  Save Report"
        )

        self.save_button.setFont(
            self.font(
                11,
                True
            )
        )

        self.save_button.setMinimumHeight(
            45
        )

        self.save_button.clicked.connect(
            self.save_text
        )

        self.save_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {PURPLE};
                color: white;
                border: none;
                border-radius: 13px;
                padding: 10px 18px;
            }}

            QPushButton:hover {{
                background-color: {PURPLE_HOVER};
            }}

            QPushButton:pressed {{
                background-color: #6D28D9;
            }}
            """
        )

        button_section.addWidget(
            self.save_button
        )


        self.clear_button = QPushButton(
            "🗑  Clear"
        )

        self.clear_button.setFont(
            self.font(
                11,
                True
            )
        )

        self.clear_button.setMinimumHeight(
            45
        )

        self.clear_button.clicked.connect(
            self.clear_text
        )

        self.clear_button.setStyleSheet(
            """
            QPushButton {
                background-color: #FEE2E2;
                color: #DC2626;
                border: 2px solid #FECACA;
                border-radius: 13px;
                padding: 10px 18px;
            }

            QPushButton:hover {
                background-color: #FECACA;
            }

            QPushButton:pressed {
                background-color: #FCA5A5;
            }
            """
        )

        button_section.addWidget(
            self.clear_button
        )

        control_layout.addLayout(
            button_section
        )

        main_layout.addWidget(
            control_card
        )

        main_layout.addSpacing(
            18
        )


        # ====================================================
        # CONTENT
        # ====================================================

        content = QHBoxLayout()

        content.setSpacing(
            20
        )


        # ====================================================
        # VERIFICATION CARD
        # ====================================================

        verification_card = QFrame()

        verification_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {CARD};
                border: 2px solid #DDD6FE;
                border-radius: 20px;
            }}
            """
        )

        verification_layout = QVBoxLayout(
            verification_card
        )

        verification_layout.setContentsMargins(
            20,
            18,
            20,
            18
        )

        self.heading = QLabel(
            "🛂 PASSPORT VERIFICATION"
        )

        self.heading.setFont(
            self.font(
                12,
                True
            )
        )

        self.heading.setStyleSheet(
            f"""
            color: {DARK};
            border: none;
            """
        )

        verification_layout.addWidget(
            self.heading
        )

        divider1 = QFrame()

        divider1.setFrameShape(
            QFrame.Shape.HLine
        )

        divider1.setStyleSheet(
            f"""
            color: {BORDER};
            border: none;
            """
        )

        verification_layout.addWidget(
            divider1
        )

        self.verification_frame = QWidget()

        self.verification_layout = QVBoxLayout(
            self.verification_frame
        )

        self.verification_layout.setContentsMargins(
            0,
            15,
            0,
            0
        )

        verification_layout.addWidget(
            self.verification_frame
        )

        self.verification_result = QLabel(
            "🌈 Awaiting document"
        )

        self.verification_result.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.verification_result.setFont(
            self.font(
                12,
                True
            )
        )

        self.verification_result.setStyleSheet(
            f"""
            color: {MUTED};
            border: none;
            """
        )

        verification_layout.addWidget(
            self.verification_result
        )

        content.addWidget(
            verification_card,
            1
        )


        # ====================================================
        # OCR CARD
        # ====================================================

        ocr_card = QFrame()

        ocr_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {CARD};
                border: 2px solid #FED7AA;
                border-radius: 20px;
            }}
            """
        )

        ocr_layout = QVBoxLayout(
            ocr_card
        )

        ocr_layout.setContentsMargins(
            20,
            18,
            20,
            18
        )

        ocr_heading = QLabel(
            "🧠 EXTRACTED INFORMATION"
        )

        ocr_heading.setFont(
            self.font(
                12,
                True
            )
        )

        ocr_heading.setStyleSheet(
            f"""
            color: {DARK};
            border: none;
            """
        )

        ocr_layout.addWidget(
            ocr_heading
        )

        divider2 = QFrame()

        divider2.setFrameShape(
            QFrame.Shape.HLine
        )

        divider2.setStyleSheet(
            f"""
            color: {BORDER};
            border: none;
            """
        )

        ocr_layout.addWidget(
            divider2
        )

        self.output_box = QTextEdit()

        self.output_box.setReadOnly(
            True
        )

        self.output_box.setFont(
            QFont(
                "Courier New",
                10
            )
        )

        self.output_box.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: #FFFBEB;
                color: {TEXT};
                border: 2px solid #FDE68A;
                border-radius: 13px;
                padding: 12px;
            }}
            """
        )

        ocr_layout.addWidget(
            self.output_box,
            1
        )

        content.addWidget(
            ocr_card,
            1
        )

        main_layout.addLayout(
            content,
            1
        )

        root_layout.addWidget(
            main,
            1
        )


        # ====================================================
        # STATUS
        # ====================================================

        self.status_label = QLabel(
            "🟢 Ready"
        )

        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.status_label.setFont(
            self.font(
                10,
                True
            )
        )

        self.status_label.setStyleSheet(
            f"""
            color: {GREEN_DARK};
            background-color: {BG};
            padding: 5px;
            """
        )

        root_layout.addWidget(
            self.status_label
        )


        # ====================================================
        # FOOTER
        # ====================================================

        footer = QLabel(
            "✨ OCR powered by Tesseract   •   "
            "PDF + Image Support   •   "
            "Passport MRZ + Aadhaar OCR"
        )

        footer.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        footer.setFont(
            self.font(
                9
            )
        )

        footer.setStyleSheet(
            f"""
            color: {MUTED};
            background-color: {BG};
            padding-bottom: 8px;
            """
        )

        root_layout.addWidget(
            footer
        )


    # ========================================================
    # DOCUMENT TYPE
    # ========================================================

    def select_passport(self):

        self.document_type = "PASSPORT"

        self.document_title.setText(
            "🛂  PASSPORT / DOCUMENT"
        )

        self.heading.setText(
            "🛂 PASSPORT VERIFICATION"
        )

        self.clear_text()


    def select_aadhaar(self):

        self.document_type = "AADHAAR"

        self.document_title.setText(
            "🪪  AADHAAR / DOCUMENT"
        )

        self.heading.setText(
            "🪪 AADHAAR VERIFICATION"
        )

        self.clear_text()


    # ========================================================
    # STATUS
    # ========================================================

    def set_status(
        self,
        text,
        color=MUTED
    ):

        self.status_label.setText(
            text
        )

        self.status_label.setStyleSheet(
            f"""
            color: {color};
            background-color: {BG};
            padding: 5px;
            """
        )


    # ========================================================
    # INVALID DOCUMENT
    # ========================================================

    def show_invalid_document_error(self):

        self.document_data = {}

        self.output_box.clear()

        self.output_box.setPlainText(

            "❌ ERROR\n\n"

            "The uploaded document does not appear "
            f"to be a {self.document_type.title()} document.\n\n"

            f"Please upload a clear "
            f"{self.document_type.title()} image or PDF."
        )

        self.verification_result.setText(
            "❌ INVALID DOCUMENT TYPE"
        )

        self.verification_result.setStyleSheet(
            f"""
            color: {DANGER};
            border: none;
            """
        )

        self.set_status(
            f"❌ Uploaded document is not detected "
            f"as {self.document_type.title()}",
            DANGER
        )

        self.clear_verification_rows()


    # ========================================================
    # LOAD DOCUMENT
    # ========================================================

    def load_document(
        self,
        file_path
    ):

        extension = os.path.splitext(
            file_path
        )[1].lower()

        if extension == ".pdf":

            try:

                pdf = fitz.open(
                    file_path
                )

                images = []

                for page in pdf:

                    matrix = fitz.Matrix(
                        2.0,
                        2.0
                    )

                    pix = page.get_pixmap(
                        matrix=matrix,
                        colorspace=fitz.csRGB,
                        alpha=False
                    )

                    image_bytes = pix.tobytes(
                        "png"
                    )

                    image_array = np.frombuffer(
                        image_bytes,
                        dtype=np.uint8
                    )

                    image = cv2.imdecode(
                        image_array,
                        cv2.IMREAD_COLOR
                    )

                    if image is not None:
                        images.append(image)

                pdf.close()

                return images

            except Exception as error:

                QMessageBox.critical(
                    self,
                    "PDF Error",
                    f"Could not open PDF.\n\n{error}"
                )

                return []

        image = cv2.imread(
            file_path
        )

        if image is None:

            QMessageBox.critical(
                self,
                "Image Error",
                "Could not read the selected image."
            )

            return []

        return [image]


    # ========================================================
    # EXTRACT
    # ========================================================

    def extract_text(self):

        file_path, _ = QFileDialog.getOpenFileName(

            self,

            f"Select {self.document_type.title()}",

            "",

            "Supported Documents "
            "(*.pdf *.jpg *.jpeg *.png);;"
            "PDF Files (*.pdf);;"
            "Image Files (*.jpg *.jpeg *.png)"
        )

        if not file_path:
            return

        self.file_label.setText(
            os.path.basename(file_path)
        )

        self.file_label.setStyleSheet(
            f"""
            color: {TEXT};
            border: none;
            """
        )

        self.set_status(
            "⏳ Loading document...",
            BLUE
        )

        QApplication.processEvents()

        images = self.load_document(
            file_path
        )

        if not images:

            self.set_status(
                "❌ Could not read document",
                DANGER
            )

            return

        all_ocr = []
        final_data = {}

        highest_aadhaar_score = -1
        highest_passport_score = -1

        for page_number, image in enumerate(
            images,
            start=1
        ):

            self.set_status(
                f"🔎 Scanning page "
                f"{page_number}/{len(images)}...",
                BLUE
            )

            QApplication.processEvents()

            if self.document_type == "PASSPORT":

                text, data = process_passport(
                    image
                )

            else:

                text, data = process_aadhaar(
                    image
                )

            all_ocr.append(
                text
            )

            current_score = data.get(
                "_score",
                0
            )

            if self.document_type == "AADHAAR":

                if current_score > highest_aadhaar_score:

                    highest_aadhaar_score = (
                        current_score
                    )

                    final_data = data.copy()

            else:

                if current_score > highest_passport_score:

                    highest_passport_score = (
                        current_score
                    )

                    final_data = data.copy()

                if (
                    data.get("MRZ")
                    and "<<" in data["MRZ"]
                ):
                    break

        self.raw_ocr_text = "\n".join(
            all_ocr
        )


        # ====================================================
        # VALIDATION
        # ====================================================

        if self.document_type == "AADHAAR":

            if highest_aadhaar_score < 5:

                self.show_invalid_document_error()

                return

        else:

            if highest_passport_score < 8:

                self.show_invalid_document_error()

                return

        final_data.pop(
            "_score",
            None
        )

        self.document_data = final_data


        # ====================================================
        # PASSPORT
        # ====================================================

        if self.document_type == "PASSPORT":

            fields = [

                "Passport Number",
                "Surname",
                "Given Names",
                "Nationality",
                "Date of Birth",
                "Sex",
                "Date of Expiry",
                "Issuing Country"
            ]

            for field in fields:

                if field not in self.document_data:

                    self.document_data[field] = (
                        "Not detected"
                    )

            self.display_passport()

            self.update_verification()

            if self.document_data.get("MRZ"):

                self.set_status(
                    "✅ Passport MRZ detected",

                )

            else:

                self.set_status(
                    "⚠️ Passport scanned using OCR",
                    ORANGE
                )


        # ====================================================
        # AADHAAR
        # ====================================================

        else:

            fields = [

                "Aadhaar Number",
                "Name",
                "Date of Birth",
                "Gender"
            ]

            for field in fields:

                if field not in self.document_data:

                    self.document_data[field] = (
                        "Not detected"
                    )

            self.display_aadhaar()

            self.update_verification()

            detected = sum(

                self.document_data.get(field)
                != "Not detected"

                for field in fields
            )

            if detected == len(fields):

                self.set_status(
                    "✅ Aadhaar information detected",
                    
                )

            elif detected > 0:

                self.set_status(
                    f"⚠️ {detected}/{len(fields)} "
                    "Aadhaar fields detected",
                    ORANGE
                )

            else:

                self.set_status(
                    "❌ Aadhaar data not detected",
                    DANGER
                )


    # ========================================================
    # DISPLAY PASSPORT
    # ========================================================

    def display_passport(self):

        self.output_box.clear()

        text = (

            "🛂 PASSPORT INFORMATION\n"

            + "─" * 48

            + "\n\n"
        )

        fields = [

            "Passport Number",
            "Surname",
            "Given Names",
            "Nationality",
            "Date of Birth",
            "Sex",
            "Date of Expiry",
            "Issuing Country"
        ]

        for field in fields:

            value = self.document_data.get(
                field,
                "Not detected"
            )

            text += (

                f"{field:<22}: "
                f"{value}\n\n"
            )

        text += (

            "🔐 MACHINE READABLE ZONE\n"

            + "─" * 48

            + "\n\n"
        )

        text += self.document_data.get(
            "MRZ",
            "Not detected"
        )

        self.output_box.setPlainText(
            text
        )


    # ========================================================
    # DISPLAY AADHAAR
    # ========================================================

    def display_aadhaar(self):

        self.output_box.clear()

        text = (

            "🪪 AADHAAR INFORMATION\n"

            + "─" * 48

            + "\n\n"
        )

        fields = [

            "Aadhaar Number",
            "Name",
            "Date of Birth",
            "Gender"
        ]

        for field in fields:

            value = self.document_data.get(
                field,
                "Not detected"
            )

            text += (

                f"{field:<22}: "
                f"{value}\n\n"
            )

        text += (

            "📋 DOCUMENT STATUS\n"

            + "─" * 48

            + "\n\n"

            + "✅ Aadhaar document detected"
        )

        self.output_box.setPlainText(
            text
        )


    # ========================================================
    # VERIFICATION ROWS
    # ========================================================

    def clear_verification_rows(self):

        while self.verification_layout.count():

            item = self.verification_layout.takeAt(
                0
            )

            widget = item.widget()

            if widget:
                widget.deleteLater()


    def update_verification(self):

        self.clear_verification_rows()

        if self.document_type == "PASSPORT":

            fields = [

                "Passport Number",
                "Surname",
                "Given Names",
                "Nationality",
                "Date of Birth",
                "Sex",
                "Date of Expiry"
            ]

        else:

            fields = [

                "Aadhaar Number",
                "Name",
                "Date of Birth",
                "Gender"
            ]

        detected = 0

        for field in fields:

            value = self.document_data.get(
                field,
                "Not detected"
            )

            valid = (
                value != "Not detected"
            )

            if valid:
                detected += 1

            row = QWidget()

            row_layout = QHBoxLayout(
                row
            )

            row_layout.setContentsMargins(
                5,
                6,
                5,
                6
            )

            icon = QLabel(
                "✓" if valid else "!"
            )

            icon.setFixedWidth(
                28
            )

            icon.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )

            icon.setFont(
                self.font(
                    13,
                    True
                )
            )

            icon.setStyleSheet(
                f"""
                color: {
                    GREEN
                    if valid
                    else ORANGE
                };

                background-color: {
                    "#DCFCE7"
                    if valid
                    else "#FEF3C7"
                };

                border-radius: 10px;
                padding: 4px;
                """
            )

            row_layout.addWidget(
                icon
            )

            label = QLabel(
                field
            )

            label.setFixedWidth(
                135
            )

            label.setFont(
                self.font(
                    10,
                    True
                )
            )

            label.setStyleSheet(
                f"""
                color: {TEXT};
                border: none;
                """
            )

            row_layout.addWidget(
                label
            )

            value_label = QLabel(
                value
            )

            value_label.setFont(
                self.font(
                    10
                )
            )

            value_label.setStyleSheet(
                f"""
                color: {
                    TEXT
                    if valid
                    else MUTED
                };

                border: none;
                """
            )

            value_label.setWordWrap(
                True
            )

            row_layout.addWidget(
                value_label,
                1
            )

            self.verification_layout.addWidget(
                row
            )

        if detected == len(fields):

            self.verification_result.setText(
                f"🎉 ALL REQUIRED "
                f"{self.document_type} "
                f"FIELDS DETECTED"
            )

            self.verification_result.setStyleSheet(
                f"""
                color: {GREEN_DARK};
                border: none;
                """
            )

        elif detected > 0:

            self.verification_result.setText(
                f"⚠️ {detected}/{len(fields)} "
                f"FIELDS DETECTED"
            )

            self.verification_result.setStyleSheet(
                f"""
                color: {ORANGE};
                border: none;
                """
            )

        else:

            self.verification_result.setText(
                f"❌ {self.document_type} "
                f"DATA NOT DETECTED"
            )

            self.verification_result.setStyleSheet(
                f"""
                color: {DANGER};
                border: none;
                """
            )


    # ========================================================
    # SAVE
    # ========================================================

    def save_text(self):

        if not self.document_data:

            QMessageBox.warning(

                self,

                "Nothing to save",

                f"Please scan a "
                f"{self.document_type.lower()} first."
            )

            return

        save_path, _ = QFileDialog.getSaveFileName(

            self,

            "Save Verification Report",

            "",

            "Text Files (*.txt)"
        )

        if not save_path:
            return

        report = (

            f"{self.document_type} "
            "VERIFICATION REPORT\n"

            + "=" * 50

            + "\n\n"
        )

        for field, value in (
            self.document_data.items()
        ):

            if field == "MRZ":
                continue

            report += (

                f"{field:<24}: "
                f"{value}\n"
            )

        if self.document_type == "PASSPORT":

            report += (

                "\nMACHINE READABLE ZONE\n"

                + "=" * 50

                + "\n\n"

                + self.document_data.get(
                    "MRZ",
                    "Not detected"
                )
            )

        try:

            with open(
                save_path,
                "w",
                encoding="utf-8"
            ) as file:

                file.write(
                    report
                )

            QMessageBox.information(

                self,

                "Saved Successfully",

                "✅ Verification report saved."
            )

        except Exception as error:

            QMessageBox.critical(

                self,

                "Save Error",

                f"Could not save report.\n\n{error}"
            )


    # ========================================================
    # CLEAR
    # ========================================================

    def clear_text(self):

        self.raw_ocr_text = ""
        self.document_data = {}

        self.output_box.clear()

        self.clear_verification_rows()

        self.file_label.setText(
            "No document selected"
        )

        self.file_label.setStyleSheet(
            f"""
            color: {MUTED};
            border: none;
            """
        )

        self.verification_result.setText(
            "🌈 Awaiting document"
        )

        self.verification_result.setStyleSheet(
            f"""
            color: {MUTED};
            border: none;
            """
        )

        self.set_status(
            "🟢 Ready",
            GREEN_DARK
        )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    app.setStyle(
        "Fusion"
    )

    window = DocumentVerification()

    window.show()

    sys.exit(
        app.exec()
    )
