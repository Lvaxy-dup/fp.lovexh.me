"""Remove an attachment and its generated fields; retain manual corrections."""
from .forms import validate


def remove_material(data,mid):
    material=next((m for m in data['materials'] if m['id']==mid),None)
    if material is None:raise KeyError(mid)
    kind=material['form'];form=data['forms'][kind]
    if form.get('budget_plan',{}).get('source',{}).get('material_id')==mid:form.pop('budget_plan',None)
    cleared=[]
    for key,meta in list(form['meta'].items()):
        if meta.get('owner')!='user' and meta.get('source',{}).get('material_id')==mid:
            data['audit'].append({'field':key,'form':kind,'before':form['values'].get(key),'after':'','owner':'material_removed','revision':data['revision']+1})
            form['values'].pop(key,None);form['meta'].pop(key,None);cleared.append(key)
    if any(k.startswith('trip.') for k in cleared):
        for key in ('start','end'):
            if key not in form['meta']:form['values'].pop(key,None)
    form['expenses']={key:item for key,item in form['expenses'].items() if item.get('source',{}).get('material_id')!=mid}
    data['materials']=[m for m in data['materials'] if m['id']!=mid]
    form.pop('generation',None)
    form['questions']=[]
    if kind in data.get('pipeline',{}).get('forms',[]):
        data['pipeline']={'status':'idle','message':'材料已移除，可重新填写当前表单。','forms':[kind],'completed':[]}
    data['audit']=data['audit'][-500:]
    validate(data,kind)
    return {'material':material,'cleared':cleared}
