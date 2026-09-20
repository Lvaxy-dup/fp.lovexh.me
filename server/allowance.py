from datetime import date,timedelta

def allowance_dates(start,end,has_fee=False):
    if not start or not end or end<start:return None
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    days=(b-a).days+1
    if days>366:return None
    return sorted({a,b}) if has_fee else [a+timedelta(days=i) for i in range(days)]
