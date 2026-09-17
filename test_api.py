#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, 'C:\\Users\\20137\\quant-dashboard')

from server.data import fetcher
import json

result = fetcher.get_risk_education('600519')
print(json.dumps(result, ensure_ascii=False, indent=2))
