# -*- coding: utf-8 -*-
import requests, json
r = requests.get('http://127.0.0.1:5000/api/crossasset/drilldown', params={'symbol':'gb_orcl'}, timeout=15)
j = r.json()
out = {'name': j.get('name'), 'n_news': len(j.get('news',[])), 'titles':[n['title'] for n in j.get('news',[])]}
open('_o.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=1))
print('done')
