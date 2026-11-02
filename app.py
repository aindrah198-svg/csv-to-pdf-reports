"""Loopback-only local UI. Uploaded data is processed in memory, not saved."""
import io
from flask import Flask, render_template, request, send_file
from playwright.sync_api import Error as BrowserError
from reports import parse_csv, render_html, pdf_from_html, ValidationError, ROOT, MAX_BYTES
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES + 64 * 1024

@app.get('/')
def index():
    return render_template('index.html', errors=[])

@app.get('/sample.csv')
def sample():
    return send_file(ROOT / 'examples' / 'sales.csv', as_attachment=True, download_name='sample-sales.csv')

@app.post('/generate')
def generate():
    upload = request.files.get('csv')
    try:
        if not upload or not upload.filename.lower().endswith('.csv'):
            raise ValidationError(['Choose a .csv file.'])
        rows = parse_csv(upload.read(MAX_BYTES + 1))
        pdf = pdf_from_html(render_html(rows, request.form.get('title','Sales performance report')))
        response = send_file(io.BytesIO(pdf),mimetype='application/pdf',as_attachment=True,download_name='sales-report.pdf')
        response.headers['Cache-Control'] = 'no-store'
        return response
    except ValidationError as e:
        return render_template('index.html', errors=e.errors), 422
    except BrowserError:
        return render_template('index.html', errors=['PDF browser unavailable. Run: python -m playwright install chromium. See README for Chrome setup.']), 503

@app.errorhandler(413)
def too_large(error):
    return render_template('index.html',errors=['Upload is too large. CSV limit: 2 MB.']),413

@app.after_request
def secure_headers(response):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'"
    return response

if __name__ == '__main__':
    app.run(host='127.0.0.1',port=8103,debug=False)
