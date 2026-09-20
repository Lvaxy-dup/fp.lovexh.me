"""Teacher-provided identity defaults, scoped to the browser's existing owner session."""
from .forms import FIELDS, patch


def profile_defaults(profile):
    values={key:profile.get(key,'') for key in ('name','department','job_title','fund_no')}
    department=values['department'].strip()
    values['fund_name']=department+'经费' if department else ''
    return values


def apply_profile(data, kind, profile, refresh=False):
    profile=profile_defaults(profile)
    form=data['forms'][kind]
    changes={}
    for key in ('name','department','job_title','fund_no','fund_name'):
        value=profile.get(key)
        if key not in FIELDS[kind] or not value:
            continue
        meta=form['meta'].get(key,{})
        from_profile=meta.get('source',{}).get('profile') is True
        # Explicit edits, including deliberately cleared cells, take precedence.
        if meta.get('owner')=='user' and not from_profile:
            continue
        current=form['values'].get(key)
        if current and not (refresh and from_profile):
            continue
        if current!=value:
            changes[key]=value
    if changes:
        patch(data,kind,changes,owner='user',source={'profile':True})
    return list(changes)
