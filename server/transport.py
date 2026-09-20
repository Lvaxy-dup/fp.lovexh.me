"""Transport invoices are charged once; inferred flight times retain provenance."""
from datetime import datetime, timedelta, time
from decimal import Decimal

from .forms import money, patch


def record_transport_invoice(data, rows, invoice_no, total, source, amounts=None):
    rows = sorted(set(rows))
    if not rows or any(type(row) is not int or not 0 <= row <= 6 for row in rows):
        raise ValueError('行程位置必须在第1至7段之间')
    invoice_no = invoice_no.strip()
    if not invoice_no:
        raise ValueError('必须使用票面真实票号，不能为去程、返程编造不同票号')
    form = data['forms']['reimbursement']
    values, meta = form['values'], form['meta']
    existing = [i for i in range(7) if values.get(f'trip.{i}.invoice') == invoice_no]
    if set(existing) - set(rows):
        raise ValueError(f'该票据已关联行程位置 {existing}，请复用这些位置并一次列出全部行程，不能重复记账')
    if any(e['invoice_no'] == invoice_no for e in form['expenses'].values()):
        raise ValueError('该票据已作为其他费用录入，不能重复计入交通费')
    for row in rows:
        if not all(values.get(f'trip.{row}.{key}') for key in ('mode', 'origin', 'destination')):
            raise ValueError('请先填写各段交通工具与起止地点，再登记票据总额')
    keys = [f'trip.{row}.{key}' for row in rows for key in ('invoice', 'fare')]
    conflicts = [key for key in keys if meta.get(key, {}).get('owner') == 'user']
    if conflicts:
        return {'conflicts': conflicts, 'error': '票号或金额已由老师修改，整张票据保留人工数据'}
    amount = str(money(total))
    # Allocate integer cents so an odd cent never changes the invoice total.
    cents, remainder = divmod(int(money(total) * 100), len(rows))
    allocations = {str(row): str(Decimal(cents + (index < remainder)) / 100) for index, row in enumerate(rows)}
    if amounts is not None:
        if set(amounts)!={str(row) for row in rows}:raise ValueError('分段金额必须覆盖全部行程位置')
        allocations={key:str(money(value)) for key,value in amounts.items()}
        if sum((money(value) for value in allocations.values()),Decimal(0))!=money(total):
            raise ValueError('分段金额合计与票面总额不一致')
    group = {'invoice_no': invoice_no, 'total': amount, 'rows': rows, 'allocation': 'explicit' if amounts is not None else 'equal', 'amounts': allocations}
    changes = {}
    for row in rows:
        changes[f'trip.{row}.invoice'] = invoice_no
        changes[f'trip.{row}.fare'] = allocations[str(row)]
    return patch(data, 'reimbursement', changes, 'agent', {**source, 'transport_invoice': group})


def estimate_flight_times(data, row, duration_minutes, reason, source, departure_time=None):
    if type(row) is not int or not 0 <= row <= 6:
        raise ValueError('行程位置超出范围')
    if type(duration_minutes) is not int or not 5 <= duration_minutes <= 1440:
        raise ValueError('飞行时长必须为5至1440分钟')
    form = data['forms']['reimbursement']
    v, meta, pre = form['values'], form['meta'], f'trip.{row}.'
    if not any(word in v.get(pre+'mode', '') for word in ('飞机', '航空', '航班')):
        raise ValueError('只能推算飞机行程')
    if not all(v.get(pre+key) for key in ('start', 'origin', 'destination')):
        raise ValueError('先根据材料填写出发日期和起止地点，不能用开票日期代替行程日期')
    def fixed(key):
        return (meta.get(pre+key, {}).get('owner') == 'user' or
                bool(v.get(pre+key)) and not meta.get(pre+key, {}).get('source', {}).get('estimated'))
    if all(v.get(pre+key) for key in ('start_time', 'end', 'end_time')):
        return {'skipped': '已有完整起止时间，保留现值'}
    duration = timedelta(minutes=duration_minutes)
    if v.get(pre+'end_time') and not v.get(pre+'start_time'):
        arrival = datetime.fromisoformat((v.get(pre+'end') or v[pre+'start'])+'T'+v[pre+'end_time'])
        departure = arrival-duration
        if departure.date().isoformat() != v[pre+'start']:
            raise ValueError('推算出发日期与已有日期冲突，请调整时长或假设')
    else:
        clock = v.get(pre+'start_time') or departure_time
        if not clock:
            raise ValueError('票面没有出发时刻，请给出 departure_time 暂定时刻并在 reason 中说明假设')
        time.fromisoformat(clock)
        departure = datetime.fromisoformat(v[pre+'start']+'T'+clock)
        arrival = departure+duration
    proposed = {'start_time': departure.strftime('%H:%M'), 'end': arrival.date().isoformat(),
                'end_time': arrival.strftime('%H:%M')}
    for key, value in proposed.items():
        if fixed(key) and v.get(pre+key) and v[pre+key] != value:
            raise ValueError('推算与已有票面或人工起止时间冲突，请调整时长或假设')
    changes = {pre+key: value for key, value in proposed.items() if not fixed(key)}
    estimate = {**source, 'estimated': True, 'reason': reason, 'duration_minutes': duration_minutes}
    return patch(data, 'reimbursement', changes, 'agent', estimate)
