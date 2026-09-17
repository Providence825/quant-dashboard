# -*- coding: utf-8 -*-
import requests, json
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Referer':'https://finance.sina.com.cn'}
def get(sym):
    r=requests.get('https://hq.sinajs.cn/list='+sym,headers=H,timeout=8)
    r.encoding='gbk'
    import re
    m=re.search(r'="([^"]*)"',r.text)
    return (m.group(1).split(',') if m else [])
out={}
for s in ['nf_RB0','nf_AU0','hf_XAU','hf_GC','hf_CL']:
    parts=get(s)
    out[s]={str(i):v for i,v in enumerate(parts)}
open('cf.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=1))
print('done')
