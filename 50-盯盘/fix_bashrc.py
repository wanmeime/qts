#!/usr/bin/env python3
with open('/home/jiaod/.bashrc', 'r') as f:
    content = f.read()
content = content.replace('\\$(', '$(')
with open('/home/jiaod/.bashrc', 'w') as f:
    f.write(content)
print('fixed')
