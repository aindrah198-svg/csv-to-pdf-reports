# Verification record

Verified locally on 2026-11-03 (Asia/Jakarta), Python 3.12, Windows, installed Google Chrome PDF engine.

- pytest: 30 tests passed. Covers exact Decimal arithmetic, paid/pending/refunded separation, invalid and missing fields, duplicate IDs, encoding, quoting, row/size limits, HTML escaping, title validation, PDF text, page numbers and Flask downloads/errors.
- Sample: 18 orders, 36 units, 12 paid orders; $2,119.40 paid, $529.85 pending and $529.85 refunded. Generated sample-report.pdf contains two pages and all 18 order IDs.
- Longer-content test: 45 records with long customer/product names remain present in the generated PDF.
- Browser: valid CSV downloads a PDF; invalid CSV shows row-numbered errors; desktop and 390px mobile checks passed with no document overflow or JavaScript errors.
- PDF visual review: both pages rendered to PNG using PDFium and inspected. Table headers repeat, text is selectable, page numbers are present, no clipped or overlapping content observed in the sample.
- Screenshots: desktop.png, mobile.png, report-page-1.png and report-page-2.png.

GitHub Actions installs Playwright Chromium on Linux and runs the suite independently. Local checks are not a production deployment, accessibility audit or source-data authenticity review.
