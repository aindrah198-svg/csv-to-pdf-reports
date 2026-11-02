"""Strict CSV validation, decimal accounting, HTML rendering and PDF generation."""
import argparse
import csv
import io
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from collections import Counter
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
HEADERS = ['order_id', 'date', 'customer', 'product', 'category', 'quantity', 'unit_price', 'status']
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500

class ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(errors))

def parse_csv(content):
    if len(content) > MAX_BYTES:
        raise ValidationError(['File exceeds the 2 MB limit.'])
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValidationError(['Use UTF-8 encoding.']) from None
    try:
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        if reader.fieldnames != HEADERS:
            raise ValidationError(['Columns must match exactly: ' + ', '.join(HEADERS)])
        rows, errors, seen = [], [], set()
        for line, raw in enumerate(reader, 2):
            if line > MAX_ROWS + 1:
                raise ValidationError(['At most 500 data rows are supported.'])
            try:
                if None in raw or any(v is None for v in raw.values()):
                    raise ValueError('Incorrect number of columns.')
                row = {k: v.strip() for k, v in raw.items()}
                if any(not v for v in row.values()):
                    raise ValueError('All fields are required.')
                if any(len(v) > 80 for v in row.values()):
                    raise ValueError('Each field must be at most 80 characters.')
                if any(any(ord(c) < 32 for c in v) for v in row.values()):
                    raise ValueError('Control characters are not allowed.')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', row['order_id']):
                    raise ValueError('Order ID must use 1-32 letters, numbers, hyphens or underscores.')
                if row['order_id'] in seen:
                    raise ValueError('Duplicate order ID: ' + row['order_id'])
                seen.add(row['order_id'])
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['date']):
                    raise ValueError('Date must use YYYY-MM-DD.')
                date.fromisoformat(row['date'])
                if not re.fullmatch(r'[1-9][0-9]{0,3}', row['quantity']):
                    raise ValueError('Quantity must be an integer from 1 to 9999.')
                if not re.fullmatch(r'(0|[1-9][0-9]{0,6})(\.[0-9]{1,2})?', row['unit_price']):
                    raise ValueError('Unit price must be 0-9999999.99 with at most two decimals, without currency symbols.')
                if row['status'] not in ('Paid', 'Pending', 'Refunded'):
                    raise ValueError('Status must be Paid, Pending or Refunded.')
                row['quantity'] = int(row['quantity'])
                row['unit_price'] = Decimal(row['unit_price'])
                row['amount'] = row['unit_price'] * row['quantity']
                rows.append(row)
            except ValueError as e:
                errors.append(f'Row {line}: {e}')
                if len(errors) >= 20:
                    errors.append('Stopped after 20 errors. Fix these and upload again.')
                    break
        if errors:
            raise ValidationError(errors)
        if not rows:
            raise ValidationError(['CSV contains no data rows.'])
        return rows
    except csv.Error as e:
        raise ValidationError(['Malformed CSV: ' + str(e)]) from None

def summarize(rows):
    total = lambda status: sum((r['amount'] for r in rows if r['status'] == status), Decimal('0'))
    categories = Counter()
    for row in rows:
        if row['status'] == 'Paid':
            categories[row['category']] += row['amount']
    paid_count = sum(r['status'] == 'Paid' for r in rows)
    return dict(count=len(rows), paid=total('Paid'), pending=total('Pending'), refunded=total('Refunded'),
                average=total('Paid') / paid_count if paid_count else Decimal('0'),
                units=sum(r['quantity'] for r in rows), paid_count=paid_count,
                start=min(r['date'] for r in rows), end=max(r['date'] for r in rows),
                categories=sorted(categories.items(), key=lambda x: (-x[1], x[0])))

env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape(['html']))
env.filters['money'] = lambda n: f'${n:,.2f}'

def render_html(rows, title='Sales performance report'):
    if not title.strip() or len(title) > 80 or any(ord(c)<32 for c in title):
        raise ValidationError(['Report title must contain 1-80 printable characters.'])
    return env.get_template('report.html').render(rows=sorted(rows,key=lambda r:(r['date'],r['order_id'])), summary=summarize(rows), title=title)

def pdf_from_html(html):
    with sync_playwright() as p:
        options = {'headless': True}
        if os.environ.get('REPORT_CHROME_CHANNEL'):
            options['channel'] = os.environ['REPORT_CHROME_CHANNEL']
        browser = p.chromium.launch(**options)
        try:
            page = browser.new_page()
            page.route('**/*', lambda route: route.abort())
            page.set_content(html, wait_until='load')
            return page.pdf(format='A4', print_background=True, display_header_footer=True,
                header_template='<span></span>', footer_template='<div style="font:9px Arial;color:#819080;width:100%;margin:0 17mm;display:flex;justify-content:space-between"><span>NORTHSTAR / CSV REPORTS</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>',
                margin={'top':'17mm','bottom':'20mm','left':'17mm','right':'17mm'})
        finally:
            browser.close()

def main():
    parser = argparse.ArgumentParser(description='Validate UTF-8 sales CSV and generate a PDF report.')
    parser.add_argument('csv', type=Path)
    parser.add_argument('--output', type=Path, default=Path('generated/report.pdf'))
    parser.add_argument('--title', default='Sales performance report')
    args = parser.parse_args()
    if args.csv.resolve() == args.output.resolve():
        parser.exit(2, 'Error: output cannot replace the input CSV.\n')
    try:
        if args.csv.stat().st_size > MAX_BYTES:
            raise ValidationError(['File exceeds the 2 MB limit.'])
        rows = parse_csv(args.csv.read_bytes())
        pdf = pdf_from_html(render_html(rows,args.title))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_bytes(pdf)
        print(f'Created {args.output}: {len(rows)} validated orders.')
    except (ValidationError, OSError) as e:
        parser.exit(2, f'Error: {e}\n')

if __name__ == '__main__':
    main()
