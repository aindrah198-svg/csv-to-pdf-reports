import csv
import io
from decimal import Decimal
import pytest
from pypdf import PdfReader
from reports import parse_csv, summarize, render_html, pdf_from_html, ValidationError, HEADERS, ROOT
from app import app

def data(**changes):
    row=dict(zip(HEADERS,['A-1','2026-10-01','Ada','Notebook','Stationery','3','0.10','Paid']))
    row.update(changes)
    out=io.StringIO(newline='')
    writer=csv.DictWriter(out,fieldnames=HEADERS)
    writer.writeheader();writer.writerow(row)
    return out.getvalue().encode()

def test_decimal_math_and_status_definitions():
    rows=parse_csv(data())+parse_csv(data(order_id='A-2',status='Pending',unit_price='2.00'))+parse_csv(data(order_id='A-3',status='Refunded',unit_price='1.00'))
    s=summarize(rows)
    assert s['paid']==Decimal('0.30')
    assert s['pending']==Decimal('6.00')
    assert s['refunded']==Decimal('3.00')
    assert s['average']==Decimal('0.30')
    assert s['count']==3 and s['units']==9

@pytest.mark.parametrize('change',[{'date':'2026-02-30'},{'date':'2026-1-01'},{'customer':''},{'quantity':'0'},{'quantity':'1.5'},{'quantity':'10000'},{'unit_price':'-1'},{'unit_price':'NaN'},{'unit_price':'1.001'},{'unit_price':'1e2'},{'status':'Unknown'},{'order_id':'bad/id'},{'product':'x'*81},{'customer':'line\nbreak'}])
def test_bad_values_report_rows(change):
    with pytest.raises(ValidationError,match='Row 2'):
        parse_csv(data(**change))

def test_bom_and_quoted_commas():
    rows=parse_csv(b'\xef\xbb\xbf'+data(customer='Lee, Ada'))
    assert rows[0]['customer']=='Lee, Ada'

def test_duplicate_ids_rejected():
    original=data().decode()
    with pytest.raises(ValidationError,match='Duplicate'):
        parse_csv((original+original.splitlines()[1]+'\n').encode())

@pytest.mark.parametrize('raw',[b'',b'bad,headers\n',b'\xff',(','.join(HEADERS)+'\n').encode(),data()+b'extra,column\n',b'x'*(2*1024*1024+1)], ids=['empty','headers','encoding','no-rows','columns','too-large'])
def test_bad_files(raw):
    with pytest.raises(ValidationError):parse_csv(raw)

def test_row_limit():
    rows=[data(order_id=f'O-{i}').decode().splitlines()[1] for i in range(501)]
    with pytest.raises(ValidationError,match='500'):parse_csv((','.join(HEADERS)+'\n'+'\n'.join(rows)).encode())

def test_autoescape_and_title_validation():
    html=render_html(parse_csv(data(customer='<script>alert(1)</script>')),'<img src=x>')
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '<img src=x>' not in html
    with pytest.raises(ValidationError):render_html(parse_csv(data()),'')

def test_empty_paid_group():
    s=summarize(parse_csv(data(status='Pending')))
    assert s['paid']==0 and s['average']==0 and s['categories']==[]

def test_sample_pdf_has_all_orders_totals_and_page_numbers():
    rows=parse_csv((ROOT/'examples/sales.csv').read_bytes())
    pdf=pdf_from_html(render_html(rows))
    reader=PdfReader(io.BytesIO(pdf))
    text='\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>=2
    for row in rows:assert row['order_id'] in text
    assert f"{summarize(rows)['paid']:,.2f}" in text
    for i,p in enumerate(reader.pages,1):assert f'Page {i} of' in p.extract_text()

def test_long_content_pdf_has_every_row():
    rows=[parse_csv(data(order_id=f'LONG-{i}',customer='A long customer name '*3,product='Detailed product name '*3))[0] for i in range(45)]
    pdf=pdf_from_html(render_html(rows,'Long content validation'))
    text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    for row in rows:assert row['order_id'] in text

def test_web_validation_and_sample():
    client=app.test_client()
    assert client.get('/').status_code==200
    assert client.get('/sample.csv').data.startswith(','.join(HEADERS).encode())
    assert client.post('/generate').status_code==422
    result=client.post('/generate',data={'csv':(io.BytesIO(b'bad'),'bad.csv')})
    assert result.status_code==422 and b'Columns must' in result.data
    assert client.post('/generate',data={'csv':(io.BytesIO(b'x'*(3*1024*1024)),'big.csv')}).status_code==413

def test_web_pdf_download():
    response=app.test_client().post('/generate',data={'csv':(io.BytesIO(data()),'sales.csv'),'title':'Test report'})
    assert response.status_code==200 and response.data.startswith(b'%PDF')
    assert response.headers['Cache-Control']=='no-store'
    assert 'attachment' in response.headers['Content-Disposition']
