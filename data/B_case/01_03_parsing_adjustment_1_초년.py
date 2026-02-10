#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional
import PyPDF2

# Handle encoding issues on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# Predefined case titles from PDF (provided by user)
CASE_TITLES = {
    '1': '드론 자격증 시험 수강 계약 불이행에 따른 환급 요구',
    '2': '학습 서비스 이용계약 해지에 따른 위약금 조정 요구',
    '3': '공무원 시험 인터넷 강의서비스 수강기간 연장 요구',
    '4': '필라테스 강습 계약의 중도해지에 따른 잔여대금 환급 요구',
    '5': '성형수술 후 부작용으로 재수술 받은 데 따른 손해배상 요구',
    '6': '피부 패키지 시술 중도해지에 따른 잔여 비용 환급 요구',
    '7': '주행 중 바퀴 파손된 전동킥보드 구입가 환급 및 치료비 배상 요구',
    '8': '노트북 하자 다발에 따른 구입대금 환급 요구',
    '9': '사업자 귀책으로 인한 결혼중개서비스 계약 해지 요구',
    '10': '결혼중개서비스 희망조건 불일치에 따른 가입비 환급 요구',
    '11': '예식서비스 보증인원 계약 불이행 환급 요구',
    '12': '하자가 지속 발생하는 반지의 반품 및 구입대금 환급 요구',
    '13': '웨딩 사진 촬영에 대한 계약해제 및 환급 요구',
    '14': '산후조리원 계약해제에 따른 계약금 환급 요구',
    '15': '코로나19 감염으로 강제퇴실한 산후조리원',
    '16': '코로나19로 인한 돌잔치 계약해제에 따른 계약금 환급 요구',
    '17': '항공권 취소로 인한 손해배상 요구',
    '18': '웹페이지 안내와 다른 호텔 객실 숙박대금 환급 요구',
    '19': '렌터카 사고 명목으로 지급한 대물면책금 및 우리비 전액 환급 요구',
}

class AdjustmentCaseParser:
    """Parse dispute adjustment cases matching the standard JSON format"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.cases = []
        self.raw_text = ""

    def extract_text_from_pdf(self) -> str:
        """Extract text from PDF file"""
        try:
            with open(self.pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                self.raw_text = text
                return text
        except Exception as e:
            print(f"Error reading PDF: {e}")
            return ""

    def parse_cases(self) -> List[Dict]:
        """Parse cases from text"""
        if not self.raw_text:
            self.extract_text_from_pdf()

        cases_data = self._split_by_case_numbers()

        for idx, case_text in enumerate(cases_data, 1):
            # Only process cases 1-19
            if idx > 19:
                break

            case_num = str(idx)
            case = self._parse_single_case(case_text, case_num)
            if case:
                # Override title with predefined correct title if available
                if case_num in CASE_TITLES:
                    case['title'] = CASE_TITLES[case_num]
                elif not case.get('title'):
                    # Skip if we have no title and no predefined title
                    continue

                self.cases.append(case)

        return self.cases

    def _split_by_case_numbers(self) -> List[str]:
        """Split text by finding '분쟁 개요' sections with preceding title"""
        pattern = r'분쟁\s*개요'
        parts = re.split(pattern, self.raw_text)

        cases = []
        for i in range(1, len(parts)):
            # Include some preceding text to get the title
            preceding_text = parts[i-1][-300:]  # Last 300 chars before '분쟁 개요'
            case_text = preceding_text + '\n분쟁 개요\n' + parts[i]
            cases.append(case_text)

        return cases

    def _parse_single_case(self, case_text: str, case_number: str) -> Optional[Dict]:
        """Parse a single case"""
        case = {
            'case_number': case_number,
            'year': self._extract_year(case_text),
            'title': self._extract_title(case_text),
            'case_type': '조정',
            'printed_page_number': self._extract_page_number(case_text),
            'overview': self._extract_overview(case_text),
            'judgement': self._extract_judgment(case_text)
        }

        # Return case even if title is empty (it will be filled from CASE_TITLES)
        return case

    def _extract_year(self, text: str) -> int:
        """Extract year from case text"""
        # Look for dates like 2021. 11. 18.
        match = re.search(r'(20\d{2})\.\s+\d+\.\s+\d+', text)
        if match:
            return int(match.group(1))
        return 0

    def _extract_title(self, text: str) -> str:
        """Extract case title - find complete title before '분쟁 개요'"""
        lines = text.split('\n')

        # Find '분쟁 개요' position
        dispute_idx = -1
        for i, line in enumerate(lines):
            if '분쟁' in line and '개요' in line:
                dispute_idx = i
                break

        if dispute_idx <= 0:
            return ""

        # Collect all meaningful lines before '분쟁 개요'
        content_lines = []

        for i in range(dispute_idx - 1, max(0, dispute_idx - 30), -1):
            line = lines[i].strip()

            if not line:
                continue

            # Skip page numbers and headers
            if (re.match(r'^[\d\s]+$', line) or
                line.startswith('사회초년생')):
                continue

            # Skip lines that are ONLY legal references or garbage
            korean_count = len(re.findall(r'[가-힣]', line))
            garbage_count = sum(1 for char in line if not re.match(r'[a-zA-Z0-9\s\uAC00-\uD7A3\-\(\)\.,]', char))

            if korean_count == 0:
                continue

            # Skip lines with excessive garbage
            if garbage_count > korean_count * 3:
                continue

            content_lines.insert(0, line)

        if not content_lines:
            return ""

        # Join all content
        combined = ' '.join(content_lines)

        # Clean up non-standard characters
        cleaned = ""
        for char in combined:
            code = ord(char)
            if (0xAC00 <= code <= 0xD7A3 or  # Korean
                0x41 <= code <= 0x5A or      # Uppercase English
                0x61 <= code <= 0x7A or      # Lowercase English
                0x30 <= code <= 0x39 or      # Numbers
                code in [0x20, 0x2D, 0x28, 0x29, 0x2E, 0x2C]):  # Space, dash, parens, period, comma
                cleaned += char

        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # Strategy: Find the part that looks like a title
        # Titles usually end with specific words and don't contain 조 법 등 legal markers much
        # Extract from the first word ending with our target words

        # Split by common legal reference markers to find title boundaries
        # Pattern: find "제XX조" which marks legal references
        parts = re.split(r'제\d+조', cleaned)

        if len(parts) > 1:
            # First part is likely the title, second part is likely legal references
            candidate = parts[0].strip()
        else:
            candidate = cleaned

        # If candidate is too short, it's probably a legal reference only
        # Use the whole cleaned text
        if len(candidate) < 8:
            candidate = cleaned

        # Remove trailing numbers
        candidate = re.sub(r'\s*\d+\s*$', '', candidate).strip()

        # Ensure it ends with a title word
        if not re.search(r'(요구|조정|보상|환급|지급|변경|취소|이행|수리|해지)\s*$', candidate):
            # If no ending word, search for it in the whole text
            match = re.search(r'(.*?)(요구|조정|보상|환급|지급|변경|취소|이행|수리|해지)', cleaned)
            if match:
                candidate = match.group(1) + match.group(2)

        candidate = re.sub(r'\s*\d+\s*$', '', candidate).strip()

        if len(candidate) > 5:
            return candidate[:150]

        return ""

    def _extract_page_number(self, text: str) -> str:
        """Extract page number"""
        # Look for page number patterns like "4 5" or single numbers
        match = re.search(r'^(\d+)\s+(\d+)', text, re.MULTILINE)
        if match:
            return match.group(1)

        match = re.search(r'[\s\n](\d+)\s*분쟁', text)
        if match:
            return match.group(1)

        return ""

    def _extract_overview(self, text: str) -> str:
        """Extract dispute overview"""
        # Match from '분쟁 개요' until '판' section starts
        # Use a more flexible pattern to catch 판 in various formats
        pattern = r'분쟁\s*개요(.*?)(?=판[\s\n]*단|판[\s\n]*$|\n\s*판)'
        match = re.search(pattern, text, re.DOTALL | re.MULTILINE)

        if match:
            overview_text = match.group(1).strip()
            # Remove sub-labels (가. 나. 다. etc.)
            overview_text = re.sub(r'^[가-타]\.\s+', '', overview_text, flags=re.MULTILINE)
            # Join multiple lines into one paragraph
            overview_text = re.sub(r'\n\s*', ' ', overview_text)
            # Clean up extra spaces
            overview_text = re.sub(r'\s+', ' ', overview_text).strip()
            return overview_text

        return ""

    def _extract_judgment(self, text: str) -> str:
        """Extract judgment"""
        # Use regex to extract judgment section
        # Pattern: find "판" (possibly with spaces/newlines after) followed by content until "위원회"
        pattern = r'판[\s\n]*(?:단)?[\s\n]+(.*?)(?=위원회|\Z)'
        match = re.search(pattern, text, re.DOTALL)

        if not match:
            return ""

        judgment_text = match.group(1).strip()

        # Remove multiple newlines and join lines
        judgment_text = re.sub(r'\n\s*', ' ', judgment_text)
        # Clean up extra spaces
        judgment_text = re.sub(r'\s+', ' ', judgment_text).strip()

        # Remove trailing garbage (non-Korean text at the end)
        # Find the last Korean character
        for i in range(len(judgment_text) - 1, -1, -1):
            code = ord(judgment_text[i])
            if 0xAC00 <= code <= 0xD7A3 or judgment_text[i] in '.다라고':
                judgment_text = judgment_text[:i+1]
                break

        return judgment_text.strip()

    def save_to_json(self, output_path: str) -> bool:
        """Save parsed cases to JSON"""
        try:
            data = {
                'total_cases': len(self.cases),
                'cases': self.cases
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[OK] Saved {len(self.cases)} cases to {output_path}")
            return True
        except Exception as e:
            print(f"[ERROR] {e}")
            return False


def main():
    pdf_path = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\B_case\01_B_parsed\02_02_AdjustmentCase\01_kca\사회초년생을 위한 분쟁조정 사례집.pdf"
    output_dir = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\B_case\01_B_parsed\02_02_AdjustmentCase\01_kca"
    output_file = Path(output_dir) / "사회초년생을 위한 분쟁조정 사례집.json"

    print("[시작] PDF 파싱 중...")
    parser = AdjustmentCaseParser(pdf_path)

    text = parser.extract_text_from_pdf()
    if text:
        print(f"[OK] PDF 추출 완료 ({len(text)} 문자)")
    else:
        print("[ERROR] PDF 읽기 실패")
        return

    cases = parser.parse_cases()
    print(f"[OK] {len(cases)} 개 사례 파싱 완료")

    parser.save_to_json(str(output_file))

    # Print sample
    if cases:
        print("\n[Sample Case #1]")
        print(f"Title: {cases[0].get('title')}")
        print(f"Year: {cases[0].get('year')}")


if __name__ == "__main__":
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
