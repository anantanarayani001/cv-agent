#!/usr/bin/env python3
"""cv_generator.py — Standardized CV PDF Generator"""

from reportlab.pdfgen import canvas as rc
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
import json, sys, re

PW, PH = A4
ML = MR = 9 * mm
MT = 8 * mm
MB = 7 * mm
CW = PW - ML - MR
LW = 32 * mm
RW = CW - LW

C_BLACK = colors.black
C_WHITE = colors.white
C_LGRAY = colors.HexColor('#F0F0F0')
C_LINK  = colors.HexColor('#0000CC')

FS_NAME  = 16.0
FS_SPIKE = 9.0
FS_SEC   = 8.5
FS_BODY  = 9.0
FS_SMALL = 8.0

H_SEC  = 13.0
H_ROW  = 12.5
H_GAP  = 3.5

FONT_REG  = 'Times-Roman'
FONT_BOLD = 'Times-Bold'

BULLET = u'■ '
DASH   = u'– '


def fmt_numbers(text):
    def replace_num(m):
        raw = m.group(0).replace(',', '')
        try:
            n = float(raw)
        except ValueError:
            return m.group(0)
        if 1900 <= n <= 2100 and '.' not in raw:
            return m.group(0)
        if n >= 1_000_000_000:
            v = round(n / 1_000_000_000, 2)
            s = ('{:.2f}'.format(v)).rstrip('0').rstrip('.')
            return s + ' bn'
        elif n >= 100_000:
            v = round(n / 1_000_000, 2)
            s = ('{:.2f}'.format(v)).rstrip('0').rstrip('.')
            return s + ' mn'
        elif n >= 1000:
            return '{:,}'.format(int(n))
        return m.group(0)
    return re.sub(r'\b\d[\d,]*(?:\.\d+)?\b', replace_num, text)


def fmt_currency(text):
    return text.replace(u'₹', 'INR ').replace('$', 'USD ').replace(u'£', 'GBP ').replace(u'€', 'EUR ')


def apply_fmt(text):
    return fmt_numbers(fmt_currency(text))


class CV:
    def __init__(self, data, out_path):
        self.d = data
        self.c = rc.Canvas(out_path, pagesize=A4)
        self.y = PH - MT

    def sw(self, t, font=FONT_REG, size=FS_BODY):
        return self.c.stringWidth(t, font, size)

    def txt(self, x, y, t, font=FONT_REG, size=FS_BODY, color=C_BLACK, align='left'):
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        {'left': self.c.drawString, 'right': self.c.drawRightString, 'center': self.c.drawCentredString}[align](x, y, t)

    def box(self, x, y, w, h, fill=C_BLACK):
        self.c.setFillColor(fill)
        self.c.rect(x, y, w, h, stroke=0, fill=1)

    def hline(self, x1, y, x2, w=0.25, color=C_BLACK):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(w)
        self.c.line(x1, y, x2, y)

    def advance(self, h):
        self.y -= h

    def lspaced(self, text, gap=1):
        return (' ' * gap).join(text)

    def wrap(self, text, max_w, font=FONT_REG, size=FS_BODY):
        words = text.split()
        lines, cur = [], ''
        for w in words:
            test = (cur + ' ' + w).strip()
            if self.sw(test, font, size) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or ['']

    def bullet(self, x, text, sub=False, year=''):
        b = DASH if sub else BULLET
        bw = self.sw(b, 'Times-Roman', FS_BODY)
        yr_w = (self.sw(year, 'Times-Roman', FS_BODY) + 4) if year else 0
        avail = (PW - MR) - x - bw - yr_w
        text = apply_fmt(text)
        lines = self.wrap(text, avail)
        total = 0
        for i, line in enumerate(lines):
            ty = self.y - 2.0
            if i == 0:
                self.txt(x, ty, b)
                self.txt(x + bw, ty, line)
                if year:
                    self.txt(PW - MR, ty, year, align='right')
            else:
                self.txt(x + bw, ty, line)
            self.advance(H_ROW)
            total += H_ROW
        return total

    def section(self, title):
        self.box(ML, self.y - H_SEC + 2, CW, H_SEC)
        ty = self.y - H_SEC + 4.0
        self.txt(ML + 2 * mm, ty, self.lspaced(title.upper(), 1),
                 font='Times-Bold', size=FS_SEC, color=C_WHITE)
        self.advance(H_SEC + 1)

    def draw_label(self, text):
        self.txt(ML + 1 * mm, self.y - 2.0, text, font='Times-Bold', size=FS_SMALL)

    def xc(self):
        return ML + LW

    def draw_header(self):
        d = self.d
        name = d.get('name', '').upper()
        gender = d.get('gender', '').upper()
        dob = d.get('dob', '')
        degree_line = d.get('degree_line', '')

        name_y = self.y - 4
        self.txt(ML, name_y, self.lspaced(name, 1), font='Times-Bold', size=FS_NAME)

        gd = (gender + ' , ' + dob) if gender and dob else (gender or dob)
        if gd:
            self.txt(PW - MR, name_y, gd, size=FS_SPIKE, align='right')
        self.advance(15)

        if degree_line:
            self.txt(PW - MR, self.y - 2, degree_line.upper(), size=FS_SPIKE, align='right')
            self.advance(11)
        else:
            self.advance(4)

    def draw_spikes(self):
        spikes = self.d.get('spike_points', [])
        if not spikes:
            return
        self.box(ML, self.y - H_SEC + 2, CW, H_SEC)
        ty = self.y - H_SEC + 4.5
        line = '   |   '.join(s.strip() for s in spikes[:4])
        self.txt(ML + CW / 2, ty, line, font='Times-Bold', size=FS_SPIKE, color=C_WHITE, align='center')
        self.advance(H_SEC + 2)

    def draw_academic_profile(self):
        entries = self.d.get('academic_profile', [])
        if not entries:
            return
        self.section('ACADEMIC PROFILE')
        c1 = 32 * mm
        c4 = 14 * mm
        c3 = 22 * mm
        c2 = CW - c1 - c3 - c4
        for i, e in enumerate(entries):
            if i % 2 == 0:
                self.box(ML, self.y - H_ROW + 2, CW, H_ROW - 2, fill=C_LGRAY)
            ty = self.y - 2.8
            self.txt(ML + 1 * mm, ty, e.get('degree', ''), size=FS_BODY)
            self.txt(ML + c1 + 1 * mm, ty, e.get('institution', ''), size=FS_BODY)
            self.txt(ML + c1 + c2 + 1 * mm, ty, e.get('score', ''), size=FS_BODY)
            self.txt(ML + c1 + c2 + c3 + 1 * mm, ty, e.get('year', ''), size=FS_BODY)
            self.hline(ML, self.y - H_ROW + 2, ML + CW, w=0.2, color=C_LGRAY)
            self.advance(H_ROW)
        self.advance(H_GAP)

    def draw_work_experience(self):
        items = self.d.get('work_experience', [])
        if not items:
            return
        self.section('WORK EXPERIENCE')
        for exp in items:
            ty = self.y - 2.0
            self.txt(ML + 1 * mm, ty, exp.get('company', ''), font='Times-Bold', size=FS_BODY)
            self.txt(self.xc() + 1 * mm, ty, exp.get('role', ''), font='Times-Bold', size=FS_BODY)
            if exp.get('duration'):
                self.txt(PW - MR, ty, exp['duration'], font='Times-Bold', size=FS_BODY, align='right')
            self.advance(H_ROW)
            for sec_key, sec_label in [('responsibilities', 'Roles & Resp.'), ('initiatives', 'Initiatives'), ('achievements', 'Achievements')]:
                pts = exp.get(sec_key, [])
                if not pts:
                    continue
                first = True
                for pt in pts:
                    if first:
                        self.draw_label(sec_label)
                        first = False
                    self.bullet(self.xc(), pt, sub=True)
        self.advance(H_GAP)

    def draw_academic_achievements(self):
        aa = self.d.get('academic_achievements', {})
        if not aa:
            return
        self.section('ACADEMIC ACHIEVEMENTS')
        for lbl, pts in [('Academic', aa.get('academic', [])), ('Competitions', aa.get('competitions', [])), ('Scholarships', aa.get('scholarships', []))]:
            if not pts:
                continue
            first = True
            for pt in pts:
                text = pt.get('text', '') if isinstance(pt, dict) else pt
                year = str(pt.get('year', '')) if isinstance(pt, dict) else ''
                if first:
                    self.draw_label(lbl)
                    first = False
                self.bullet(self.xc(), text, year=year)
        self.advance(H_GAP)

    def draw_por(self):
        por = self.d.get('positions_of_responsibility', [])
        if not por:
            return
        self.section('POSITIONS OF RESPONSIBILITY')
        for e in por:
            ty = self.y - 2.0
            self.txt(ML + 1 * mm, ty, e.get('organization', ''), font='Times-Bold', size=FS_BODY)
            self.txt(self.xc() + 1 * mm, ty, e.get('role', ''), font='Times-Bold', size=FS_BODY)
            year = str(e.get('year', ''))
            if year:
                self.txt(PW - MR, ty, year, font='Times-Bold', size=FS_BODY, align='right')
            self.advance(H_ROW)
            for pt in e.get('bullets', []):
                self.bullet(self.xc(), pt, sub=True)
        self.advance(H_GAP)

    def draw_cip(self):
        cip = self.d.get('cip', {})
        if not cip:
            return
        all_entries = []
        for key in ('certifications', 'internships', 'projects'):
            all_entries.extend(cip.get(key, []))
        if not all_entries:
            return
        self.section('CERTIFICATIONS, INTERNSHIPS & PROJECTS')
        for e in all_entries:
            ty = self.y - 2.0
            self.txt(ML + 1 * mm, ty, e.get('organization', ''), font='Times-Bold', size=FS_BODY)
            self.txt(self.xc() + 1 * mm, ty, e.get('title', ''), font='Times-Bold', size=FS_BODY)
            if e.get('duration'):
                self.txt(PW - MR, ty, e['duration'], font='Times-Bold', size=FS_BODY, align='right')
            self.advance(H_ROW)
            for pt in e.get('bullets', []):
                self.bullet(self.xc(), pt, sub=True)
        self.advance(H_GAP)

    def draw_eca(self):
        eca = self.d.get('eca', {})
        if not eca:
            return
        self.section('EXTRA CURRICULAR ACTIVITIES')
        ORDER = ['Debate/ Public Speaking', 'Sports / Adventure Sports', 'Management', 'Cultural', 'Art & Design', 'Quizzing', 'Social Service', 'Technical', 'Literature', 'Others']
        extra = [k for k in eca if k not in ORDER]
        for cat in ORDER + extra:
            pts = eca.get(cat, [])
            if not pts:
                continue
            first = True
            for pt in pts:
                text = pt.get('text', '') if isinstance(pt, dict) else pt
                year = str(pt.get('year', '')) if isinstance(pt, dict) else ''
                if first:
                    self.draw_label(cat)
                    first = False
                self.bullet(self.xc(), text, year=year if year else '')
        self.advance(H_GAP)

    def draw_footer(self):
        d = self.d
        parts = [p for p in [d.get('linkedin'), d.get('email'), d.get('phone')] if p]
        if not parts:
            return
        self.c.setFont('Times-Roman', FS_SMALL)
        self.c.setFillColor(C_LINK)
        self.c.drawCentredString(ML + CW / 2, MB + 2, '   |   '.join(parts))

    def generate(self):
        self.draw_header()
        self.draw_spikes()
        self.draw_academic_profile()
        self.draw_work_experience()
        self.draw_academic_achievements()
        self.draw_por()
        self.draw_cip()
        self.draw_eca()
        self.draw_footer()
        self.c.save()
        return self.d.get('name', 'CV')


def main():
    if len(sys.argv) < 3:
        print("Usage: python cv_generator.py <data.json> <output.pdf>")
        sys.exit(1)
    with open(sys.argv[1], encoding='utf-8') as f:
        data = json.load(f)
    cv = CV(data, sys.argv[2])
    name = cv.generate()
    print("CV generated for " + name + ": " + sys.argv[2])


if __name__ == '__main__':
    main()
