"""Conservative checks against OCR text; ambiguous totals must be reviewed."""
import re
import unicodedata
from .forms import money

NUMBER=r'(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d{1,9})(?:\.\d{1,2})?(?![\d.])'
LABEL=r'价税合计|小写|实付金额|合计金额|票价合计|总金额|总价|合计'

def verify_invoice_amount(text,total,amounts=None):
    text=unicodedata.normalize('NFKC',text)
    text=re.sub(r'<[^>]*>',' ',text)
    candidates={};grand_totals={}
    for label in re.finditer(LABEL,text):
        tail=text[label.end():label.end()+160]
        # Do not accidentally scan into another labelled field or invoice.
        tail=re.split(r'发票号码|开票日期|购买方|销售方',tail)[0]
        match=re.search(NUMBER,tail)
        if match:
            try:amount=money(match.group().replace(',',''))
            except ValueError:continue
            quote=text[label.start():label.end()+match.end()]
            candidates[amount]=quote
            if label.group() in ('价税合计','小写','实付金额'):grand_totals[amount]=quote
    # Invoices commonly show a pre-tax 合计 row before the actual 价税合计.
    if grand_totals:candidates=grand_totals
    expected=money(total)
    if len(candidates)!=1:
        raise ValueError('票面总额缺失或存在多个不同合计，请重新核对材料；不能猜测票据金额')
    if expected not in candidates:
        raise ValueError('登记金额与材料标注的票面合计不一致，请使用真实价税合计')
    if amounts:
        visible={money(m.group().replace(',','')) for m in re.finditer(NUMBER,text) if len(m.group().replace(',','').split('.')[0])<=8}
        if any(money(value) not in visible for value in amounts.values()):
            raise ValueError('分段金额必须来自票面明细；只有总额时不要传 amounts，由程序均分')
    return {'total':str(expected),'quote':candidates[expected]}
